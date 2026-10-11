"""Read-only SELECT against disposable synthetic leads, never Render/glass_leads."""
from quote_lab.postgres_store import test_database_parameters
from crm_lab.lead_preview import preview_leads, LeadPreviewError

class PostgresLeadPreview:
    def __init__(self,test_database_url):
        self.parameters=test_database_parameters(test_database_url)

    def snapshot(self,limit=300):
        if type(limit) is not int or not 1<=limit<=300:
            raise LeadPreviewError('Preview limit must be 1..300')
        import psycopg2
        from psycopg2.extras import RealDictCursor
        connection=psycopg2.connect(**self.parameters)
        try:
            connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SET LOCAL statement_timeout='5s'")
                    cur.execute("""SELECT current_database() AS name,rolsuper,rolcreatedb,rolcreaterole,
                        current_setting('transaction_read_only') AS read_only
                        FROM pg_roles WHERE rolname=current_user""")
                    target=cur.fetchone()
                    if (target['name']!='quote_lab_test' or target['rolsuper'] or target['rolcreatedb']
                            or target['rolcreaterole'] or target['read_only']!='on'):
                        raise LeadPreviewError('Read-only disposable database and limited role required')
                    cur.execute("""SELECT phone,name,product,status,callback_time,notes,updated_at
                        FROM crm_preview_stage.leads ORDER BY updated_at DESC,phone LIMIT %s""",(limit+1,))
                    rows=[dict(row) for row in cur.fetchall()]
            return preview_leads(rows[:limit],has_more=len(rows)>limit)
        finally:
            connection.close()
