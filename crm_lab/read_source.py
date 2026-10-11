"""Prepared source reader; live reads are OFF unless separately authorized/configured."""
from datetime import datetime,timezone
from quote_lab.postgres_store import test_database_parameters
from crm_lab.lead_preview import LeadPreviewError,map_leads

class ReadOnlyLeadSource:
    def __init__(self,*,test_database_url=None,live_parameters=None,live_enabled=False):
        if type(live_enabled) is not bool or (test_database_url is not None and live_parameters is not None):
            raise LeadPreviewError('Choose one explicit source configuration')
        self.fixture=test_database_url is not None
        self.enabled=self.fixture or live_enabled
        self.parameters=test_database_parameters(test_database_url) if self.fixture else live_parameters
        if not self.fixture and live_enabled:
            required={'host','dbname','user','password','sslmode','connect_timeout'}
            if (not isinstance(live_parameters,dict) or set(live_parameters)!=required
                    or not all(isinstance(live_parameters[k],str) and live_parameters[k] for k in required-{'connect_timeout'})
                    or live_parameters['sslmode']!='verify-full' or live_parameters['connect_timeout']!=5):
                raise LeadPreviewError('Explicit TLS-verified source configuration required')
    def page(self,*,limit,after=''):
        if not self.enabled:raise LeadPreviewError('Live source is disabled pending owner approval')
        if type(limit) is not int or not 1<=limit<=300 or not isinstance(after,str) or len(after)>20:
            raise LeadPreviewError('Invalid source page')
        import psycopg2
        from psycopg2.extras import RealDictCursor
        connection=psycopg2.connect(**self.parameters)
        try:
            connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SET LOCAL statement_timeout='5s'")
                    cur.execute("""SELECT rolsuper,rolcreatedb,rolcreaterole,current_database() AS name,
                        current_setting('transaction_read_only') AS read_only
                        FROM pg_roles WHERE rolname=current_user""")
                    role=cur.fetchone()
                    if role['rolsuper'] or role['rolcreatedb'] or role['rolcreaterole'] or role['read_only']!='on':
                        raise LeadPreviewError('Limited read-only source role required')
                    if self.fixture and role['name']!='quote_lab_test':raise LeadPreviewError('Wrong fixture database')
                    # These are fixed trusted identifiers, never request-supplied tables.
                    table='crm_preview_stage.leads' if self.fixture else 'public.glass_leads'
                    cur.execute(f"""SELECT phone,name,product,status,callback_time,notes,updated_at
                        FROM {table} WHERE phone>%s ORDER BY phone LIMIT %s""",(after,limit+1))
                    rows=[dict(row) for row in cur.fetchall()]
            result=map_leads(rows[:limit],has_more=len(rows)>limit,synthetic=self.fixture)
            result.update(next_after=rows[limit-1]['phone'] if len(rows)>limit else None,
                          observed_at=datetime.now(timezone.utc).isoformat(),snapshot_scope='single_page')
            return result
        finally:connection.close()
