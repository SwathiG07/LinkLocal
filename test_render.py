from linklocal.superuser.dashboard import app, build_dashboard_snapshot
import os
os.environ['FLASK_ENV'] = 'development'
with app.app_context():
    from flask import render_template
    try:
        snapshot = dict(build_dashboard_snapshot(set()))
        html = render_template('index.html', groups=snapshot['groups'], peer_map=snapshot['peer_map'], logs=snapshot['logs'], enabled_logs=set(), format_timestamp=lambda x:x)
        print("Success, length:", len(html))
    except Exception as e:
        import traceback
        traceback.print_exc()
