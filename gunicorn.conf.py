"""Start Yossi's durable queue after the bot WSGI app loads, never in the CRM reader."""


def post_worker_init(worker):
    # This repository also deploys crm_lab.runtime:create_application().
    # Never import or start the bot from that separate read-only service.
    if getattr(worker.app, 'app_uri', None) != 'app:app':
        return
    from app import ensure_worker_started
    ensure_worker_started()
