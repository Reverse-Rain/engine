
# ...existing code...
from backend import get_dashboard_data, save_job_post
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from urllib.parse import urlparse, urljoin
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from backend import analyze_cv_with_jd_and_update_candidate
import json
import os
import urllib.request
import urllib.error
import hmac
import hashlib
from dotenv import load_dotenv

load_dotenv(override=True)

# ----------------------------------------------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Change this to a secure random value

# ---------------- External Integrations (Teams) ----------------
# Optional: set TEAMS_WEBHOOK_URL in your environment / .env to enable Microsoft Teams channel posts.
# You can also set APP_BASE_URL (defaults to http://localhost:5000) for deep links in the card.
TEAMS_WEBHOOK_URL = os.getenv('TEAMS_WEBHOOK_URL')
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:5000')
LINK_TOKEN_SECRET = os.getenv('LINK_TOKEN_SECRET', app.secret_key)

def generate_link_token(path: str, username: str):
    msg = f"{username}:{path}".encode('utf-8')
    return hmac.new(LINK_TOKEN_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()

def verify_link_token(path: str, username: str, token: str):
    if not (username and token):
        return False
    expected = generate_link_token(path, username)
    return hmac.compare_digest(expected, token)

def send_teams_notification(notification: dict):
    """Post a notification to a Microsoft Teams channel via Incoming Webhook (if configured).

    Expects TEAMS_WEBHOOK_URL env variable. Silently no-ops if missing or errors occur.
    Uses an Adaptive Card (fallback simple text if card fails) with candidate context & deep link.
    """
    if not TEAMS_WEBHOOK_URL:
        return  # integration not enabled
    try:
        title = notification.get('type', 'Notification').replace('_', ' ').title()
        candidate_name = notification.get('candidate_name') or 'Unknown'
        position = notification.get('position') or 'N/A'
        message = notification.get('message') or ''
        cid = notification.get('candidate_id')
        # Embed signed token link if we have a specific receiver
        receiver = notification.get('receiver_username') or ''
        if cid and receiver:
            path = f"/candidate/{cid}"
            token = generate_link_token(path, receiver)
            view_url = f"{APP_BASE_URL}/candidate_link/{cid}?user={receiver}&token={token}"
        else:
            view_url = f"{APP_BASE_URL}/candidate/{cid}" if cid else APP_BASE_URL
        # Minimal Adaptive Card payload
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "msteams": {"width": "Full"},
                        "body": [
                            {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
                            {"type": "TextBlock", "wrap": True, "text": message},
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Candidate", "value": candidate_name},
                                    {"title": "Position", "value": position},
                                    {"title": "Priority", "value": notification.get('priority','normal')},
                                    {"title": "Action Required", "value": 'Yes' if notification.get('action_required') else 'No'}
                                ]
                            }
                        ],
                        "actions": [
                            {"type": "Action.OpenUrl", "title": "View Candidate", "url": view_url}
                        ]
                    }
                }
            ]
        }
        data = json.dumps(card).encode('utf-8')
        req = urllib.request.Request(TEAMS_WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 (intentional external call)
            _ = resp.read()
    except Exception as e:  # pragma: no cover - non critical
        try:
            print('Teams webhook send failed:', e)
        except Exception:
            pass

# ---------------- Workflow Reminder Configuration ----------------
REMINDER_THRESHOLD_HOURS = 24          # Hours until first pending escalation
REMINDER_REPEAT_HOURS = 24             # Minimum hours between repeated reminders for same stage

def parse_iso(dt_str):
    try:
        dt = datetime.datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            # Assume UTC if no timezone info
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None

def load_candidates():
    path = os.path.join('db','candidates.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path,'r',encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_candidates(cands):
    path = os.path.join('db','candidates.json')
    with open(path,'w',encoding='utf-8') as f:
        json.dump(cands,f,indent=4)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User model
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

    def get_id(self):
        return str(self.id)

# Load users from candidates.json (for demo, use email as username)
def load_users():
    users = {}
    with open(os.path.join('db', 'userdata.json'), 'r') as f:
        users_data = json.load(f)
        for user in users_data:
            users[user['username']] = {
                'id': user['user_id'],
                'password': user['password'],
                'name': user['username'],
                'role': user.get('role'),
                'department': user.get('department')
            }
    return users

users_data = load_users()

# ----------------------------------------------------------------------------------------------------------------

@login_manager.user_loader
def load_user(user_id):
    for username, user in users_data.items():
        if str(user['id']) == str(user_id):
            return User(user['id'], username)
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Support redirecting back to originally requested page via ?next= param (added by flask-login)
    def is_safe_url(target):
        try:
            ref_url = urlparse(request.host_url)
            test_url = urlparse(urljoin(request.host_url, target))
            return (test_url.scheme in ('http','https') and ref_url.netloc == test_url.netloc)
        except Exception:
            return False
    next_url = request.args.get('next')
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = users_data.get(username)
        if user and user['password'] == password:
            user_obj = User(user['id'], username)
            login_user(user_obj)
            # Prefer safe next redirect if provided
            target = next_url if next_url and is_safe_url(next_url) else url_for('index')
            resp = redirect(target)
            # set simple cookies for role/username used by frontend notification polling
            resp.set_cookie('role', user.get('role',''), httponly=False, samesite='Lax')
            resp.set_cookie('username', username, httponly=False, samesite='Lax')
            return resp
        else:
            return render_template('login.html', is_logged_in=False, error="Invalid credentials")
    return render_template('login.html', is_logged_in=False, next=next_url)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    resp = redirect(url_for('login'))
    resp.delete_cookie('role')
    resp.delete_cookie('username')
    return resp


# ----------------------------------------------------------------------------------------------------------------



@app.route('/')
@login_required
def index():
    dashboard_data = get_dashboard_data()
    return render_template(
        'index.html',
        is_logged_in=True,
        user_id=current_user.get_id(),
        username=current_user.username,
        **dashboard_data
    )

# ----------------------------------------------------------------------------------------------------------------
# --- Hierarchical HR Team Management Page ---
@app.route('/manage_hr_team')
@login_required
def manage_hr_team():
    """Render the HR Team Management page with hierarchical approval cycle data using robust notification/history logic."""
    users_path = os.path.join('db', 'userdata.json')
    cand_path = os.path.join('db', 'candidates.json')
    notif_path = os.path.join('db', 'notifications.json')
    users = []
    candidates = []
    notifications = []
    if os.path.exists(users_path):
        with open(users_path, 'r', encoding='utf-8') as f:
            users = json.load(f)
    if os.path.exists(cand_path):
        with open(cand_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    if os.path.exists(notif_path):
        with open(notif_path, 'r', encoding='utf-8') as f:
            notifications = json.load(f)

    view_filter = request.args.get('filter', 'overall')

    def build_hierarchical_approval_flow(candidates, notifications, users, view_filter='overall'):
        discipline_managers = [u for u in users if u.get('role') == 'Discipline Manager']
        department_managers = [u for u in users if u.get('role') in ['Department Manager (MOE)', 'Department Manager (MOP)']]
        operation_managers = [u for u in users if u.get('role') == 'Operation Manager']

        if view_filter == 'active':
            filtered_candidates = [c for c in candidates if c.get('status', '').lower() not in ['hired', 'rejected', 'withdrawn']]
        else:
            filtered_candidates = candidates

        hierarchical_flow = {
            'discipline_managers': [],
            'department_managers': [],
            'operation_managers': []
        }

        # Discipline Managers
        for i, manager in enumerate(discipline_managers):
            manager_username = manager.get('username', '')
            manager_data = {
                'id': manager.get('user_id', manager_username),
                'name': manager_username.title().replace('_', ' '),
                'role': manager.get('role', ''),
                'department': manager.get('department', ''),
                'shortlisted': [],
                'onhold': [],
                'notapproved': []
            }
            for candidate in filtered_candidates:
                candidate_info = {
                    'id': candidate.get('id'),
                    'name': candidate.get('name', 'Unknown'),
                    'position': candidate.get('position', ''),
                    'status': candidate.get('status', '')
                }
                candidate_notifications = [n for n in notifications if 
                                         n.get('candidate_id') == candidate.get('id') and 
                                         n.get('for_role') == 'Discipline Manager' and
                                         n.get('approved_by') == manager_username]
                if candidate_notifications:
                    latest_notification = max(candidate_notifications, key=lambda x: x.get('timestamp', ''))
                    notification_status = latest_notification.get('status', 'Pending')
                    if notification_status == 'Approved':
                        manager_data['shortlisted'].append(candidate_info)
                    elif notification_status == 'Rejected':
                        manager_data['notapproved'].append(candidate_info)
                    else:
                        manager_data['onhold'].append(candidate_info)
                else:
                    status_updated_by = candidate.get('status_updated_by', '')
                    status_updated_by_role = candidate.get('status_updated_by_role', '')
                    if (status_updated_by == manager_username or 
                        (status_updated_by_role == 'Discipline Manager' and status_updated_by == manager_username)):
                        candidate_status = candidate.get('status', '').lower()
                        if candidate_status in ['shortlisted', 'approved', 'hired']:
                            manager_data['shortlisted'].append(candidate_info)
                        elif candidate_status in ['rejected']:
                            manager_data['notapproved'].append(candidate_info)
                        else:
                            manager_data['onhold'].append(candidate_info)
                    else:
                        status_history = candidate.get('status_history', [])
                        for history_entry in status_history:
                            if (history_entry.get('updated_by') == manager_username or
                                (history_entry.get('updated_by_role') == 'Discipline Manager' and 
                                 history_entry.get('updated_by') == manager_username)):
                                candidate_status = candidate.get('status', '').lower()
                                if candidate_status in ['shortlisted', 'approved', 'hired', 'interviewed', 'interview scheduled']:
                                    manager_data['shortlisted'].append(candidate_info)
                                elif candidate_status in ['rejected']:
                                    manager_data['notapproved'].append(candidate_info)
                                else:
                                    manager_data['onhold'].append(candidate_info)
                                break
            hierarchical_flow['discipline_managers'].append(manager_data)

        # Department Managers
        for i, manager in enumerate(department_managers):
            manager_username = manager.get('username', f'dept_mgr_{i}')
            manager_data = {
                'id': manager.get('user_id', manager_username),
                'name': manager.get('username', 'Unknown').title().replace('_', ' '),
                'role': manager.get('role', ''),
                'department': manager.get('department', ''),
                'shortlisted': [],
                'onhold': [],
                'notapproved': []
            }
            for candidate in filtered_candidates:
                candidate_info = {
                    'id': candidate.get('id'),
                    'name': candidate.get('name', 'Unknown'),
                    'position': candidate.get('position', ''),
                    'status': candidate.get('status', '')
                }
                dept_notifications = [n for n in notifications if 
                                    n.get('candidate_id') == candidate.get('id') and 
                                    n.get('for_role') in ['Department Manager (MOE)', 'Department Manager (MOP)'] and
                                    n.get('approved_by') == manager_username]
                if dept_notifications:
                    latest_notification = max(dept_notifications, key=lambda x: x.get('timestamp', ''))
                    notification_status = latest_notification.get('status', 'Pending')
                    if notification_status == 'Approved':
                        manager_data['shortlisted'].append(candidate_info)
                    elif notification_status == 'Rejected':
                        manager_data['notapproved'].append(candidate_info)
                    else:
                        manager_data['onhold'].append(candidate_info)
                else:
                    status_updated_by = candidate.get('status_updated_by', '')
                    status_updated_by_role = candidate.get('status_updated_by_role', '')
                    if (status_updated_by == manager_username or 
                        (status_updated_by_role in ['Department Manager (MOE)', 'Department Manager (MOP)'] and 
                         status_updated_by == manager_username)):
                        candidate_status = candidate.get('status', '').lower()
                        if candidate_status in ['shortlisted', 'approved', 'hired']:
                            manager_data['shortlisted'].append(candidate_info)
                        elif candidate_status in ['rejected']:
                            manager_data['notapproved'].append(candidate_info)
                        else:
                            manager_data['onhold'].append(candidate_info)
                    else:
                        status_history = candidate.get('status_history', [])
                        for history_entry in status_history:
                            if (history_entry.get('updated_by') == manager_username or
                                (history_entry.get('updated_by_role') in ['Department Manager (MOE)', 'Department Manager (MOP)'] and 
                                 history_entry.get('updated_by') == manager_username)):
                                candidate_status = candidate.get('status', '').lower()
                                if candidate_status in ['shortlisted', 'approved', 'hired', 'interviewed', 'interview scheduled']:
                                    manager_data['shortlisted'].append(candidate_info)
                                elif candidate_status in ['rejected']:
                                    manager_data['notapproved'].append(candidate_info)
                                else:
                                    manager_data['onhold'].append(candidate_info)
                                break
            hierarchical_flow['department_managers'].append(manager_data)

        # Operation Managers
        for i, manager in enumerate(operation_managers):
            manager_username = manager.get('username', f'op_mgr_{i}')
            manager_data = {
                'id': manager.get('user_id', manager_username),
                'name': manager.get('username', 'Unknown').title().replace('_', ' '),
                'role': manager.get('role', ''),
                'department': manager.get('department', ''),
                'shortlisted': [],
                'onhold': [],
                'notapproved': []
            }
            for candidate in filtered_candidates:
                candidate_id = candidate.get('id')
                candidate_status = candidate.get('status', '').lower()
                candidate_info = {
                    'id': candidate.get('id'),
                    'name': candidate.get('name', 'Unknown'),
                    'position': candidate.get('position', ''),
                    'status': candidate.get('status', '')
                }
                op_notifications = [n for n in notifications if 
                                  n.get('candidate_id') == candidate_id and 
                                  n.get('for_role') == 'Operation Manager' and
                                  n.get('approved_by') == manager_username]
                if op_notifications:
                    latest_notification = max(op_notifications, key=lambda x: x.get('timestamp', ''))
                    notification_status = latest_notification.get('status', 'Pending')
                    if notification_status == 'Approved':
                        manager_data['shortlisted'].append(candidate_info)
                    elif notification_status == 'Rejected':
                        manager_data['notapproved'].append(candidate_info)
                    else:
                        manager_data['onhold'].append(candidate_info)
                else:
                    status_updated_by = candidate.get('status_updated_by', '')
                    status_updated_by_role = candidate.get('status_updated_by_role', '')
                    if (status_updated_by == manager_username or 
                        (status_updated_by_role == 'Operation Manager' and status_updated_by == manager_username)):
                        if candidate_status == 'hired':
                            manager_data['shortlisted'].append(candidate_info)
                        elif candidate_status in ['approved']:
                            manager_data['shortlisted'].append(candidate_info)
                        elif candidate_status in ['rejected']:
                            manager_data['notapproved'].append(candidate_info)
                        else:
                            manager_data['onhold'].append(candidate_info)
                    else:
                        status_history = candidate.get('status_history', [])
                        for history_entry in status_history:
                            if (history_entry.get('updated_by') == manager_username or
                                (history_entry.get('updated_by_role') == 'Operation Manager' and 
                                 history_entry.get('updated_by') == manager_username)):
                                if candidate_status in ['hired', 'approved', 'interviewed', 'interview scheduled', 'shortlisted']:
                                    manager_data['shortlisted'].append(candidate_info)
                                elif candidate_status in ['rejected']:
                                    manager_data['notapproved'].append(candidate_info)
                                else:
                                    manager_data['onhold'].append(candidate_info)
                                break
            hierarchical_flow['operation_managers'].append(manager_data)

        return hierarchical_flow

    hierarchical_data = build_hierarchical_approval_flow(candidates, notifications, users, view_filter)
    current_user_role = get_user_role(current_user.username)
    return render_template(
        'manage_hr_team.html',
        hierarchical_data=hierarchical_data,
        current_user_role=current_user_role,
        view_filter=view_filter,
        is_logged_in=True,
        username=current_user.username
    )


@app.route('/post_jobs', methods=['GET', 'POST'])
@login_required
def post_jobs():
    if request.method == 'POST':
        form = request.form
        file = request.files.get('jd_file')
        if not file or file.filename == '':
            flash('Job Description file is required.', 'danger')
            return render_template('post_jobs.html')
        posted_by = current_user.username

        # Handle auto shortlisting and match score
        auto_shortlisting = form.get('auto_shortlisting') == '1'
        match_score = int(form.get('match_score', 75))
        session['auto_shortlisting'] = auto_shortlisting
        session['match_score'] = match_score

        # Save job post with extra fields
        job = save_job_post(form, file, posted_by, auto_shortlisting=auto_shortlisting, match_score=match_score)
        flash('Job posted successfully!', 'success')
        job_id = job.get('job_id') if isinstance(job, dict) else None
        if job_id:
            return redirect(url_for('jobs_list', animate='1', highlight_job_id=job_id))
        return redirect(url_for('jobs_list', animate='1'))
    return render_template('post_jobs.html')


# Route for jobs list
@app.route('/jobs_list')
@login_required

def jobs_list():
    # Load jobs from db/jobs.json
    jobs = []
    jobs_path = os.path.join('db', 'jobs.json')
    if os.path.exists(jobs_path):
        with open(jobs_path, 'r', encoding='utf-8') as f:
            try:
                jobs = json.load(f)
            except Exception:
                jobs = []

    # Use session to persist filters
    changed = False
    for param, default in [('view', 'table'), ('sort', 'newest'), ('status', 'all')]:
        val = request.args.get(param)
        if val is not None:
            session['jobs_list_' + param] = val
            changed = True
    # Always update animate from query

    animate = request.args.get('animate', '0')
    highlight_job_id = request.args.get('highlight_job_id')

    # Use session or default for each param
    view = session.get('jobs_list_view', 'table')
    sort = session.get('jobs_list_sort', 'newest')
    status = session.get('jobs_list_status', 'all')

    # Filter by status
    if status == 'active':
        jobs = [job for job in jobs if str(job.get('status', 'active')).lower() in ['active', 'open']]
    elif status == 'closed':
        jobs = [job for job in jobs if str(job.get('status', '')).lower() == 'closed']

    # Sort jobs
    def get_job_date(job):
        # Try to use a date field, fallback to job_id as int
        return job.get('created_at') or job.get('date_posted') or int(job.get('job_id', 0))
    reverse = (sort == 'newest')
    jobs = sorted(jobs, key=get_job_date, reverse=reverse)

    return render_template(
        'jobs_list.html',
        jobs=jobs,
        view=view,
        sort=sort,
        status=status,
        animate=animate,
        highlight_job_id=highlight_job_id,
        is_logged_in=True,
        username=current_user.username
    )

# ---------------- Manage Candidates ----------------
@app.route('/manage_candidates')
@app.route('/managecandidates')  # alias without underscore
@login_required
def manage_candidates():
    """Render the Manage Candidates page with table/card views.
    Query params:
      view=table|card (default table)
    """
    # Load candidates from db
    candidates = []
    cand_path = os.path.join('db', 'candidates.json')
    if os.path.exists(cand_path):
        try:
            with open(cand_path, 'r', encoding='utf-8') as f:
                candidates = json.load(f)
        except Exception:
            candidates = []

    view = request.args.get('view', 'table')
    if view not in ['table', 'card']:
        view = 'table'

    return render_template(
        'manage_candidates.html',
        candidates_list=candidates,
        view=view,
        is_logged_in=True,
        username=current_user.username
    )

@app.route('/job_details/<job_id>')
@login_required
def job_details(job_id):
    # Load jobs from db/jobs.json
    jobs = []
    jobs_path = os.path.join('db', 'jobs.json')
    if os.path.exists(jobs_path):
        with open(jobs_path, 'r', encoding='utf-8') as f:
            try:
                jobs = json.load(f)
            except Exception:
                jobs = []
    # Find job by id
    job = next((j for j in jobs if str(j.get('job_id')) == str(job_id)), None)
    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('jobs_list'))
    # Load candidates for this job
    candidates = []
    candidates_path = os.path.join('db', 'candidates.json')
    if os.path.exists(candidates_path):
        with open(candidates_path, 'r', encoding='utf-8') as f:
            try:
                all_candidates = json.load(f)
                candidates = [c for c in all_candidates if str(c.get('job_id')) == str(job_id)]
            except Exception:
                candidates = []
    # Fix JD file path for preview/download
    jdfile = job.get('jd_file_path', '')
    if jdfile.startswith('uploads/'):
        jdfile_url = jdfile[len('uploads/'):]  # remove uploads/ prefix
    elif jdfile:
        jdfile_url = jdfile
    else:
        jdfile_url = ''

    # Calculate job status info for popup
    import datetime
    posted_at = job.get('posted_at')
    lead_time = int(job.get('job_lead_time', 0) or 0)
    total_openings = int(job.get('job_openings', 0) or 0)
    hired_count = sum(1 for c in candidates if c.get('status', '').lower() == 'hired')
    posted_date = None
    closing_date = None
    days_remaining = None
    is_expired = False
    is_filled = False
    if posted_at:
        try:
            posted_date = datetime.datetime.strptime(posted_at, '%Y-%m-%d %H:%M:%S')
            closing_date = posted_date + datetime.timedelta(days=lead_time)
            days_remaining = (closing_date - datetime.datetime.now()).days
            is_expired = days_remaining < 0
        except Exception:
            posted_date = None
            closing_date = None
            days_remaining = None
    if total_openings > 0 and hired_count >= total_openings:
        is_filled = True
    job_status_info = {
        'posted_date': posted_date.strftime('%Y-%m-%d') if posted_date else '',
        'closing_date': closing_date.strftime('%Y-%m-%d') if closing_date else '',
        'days_remaining': days_remaining,
        'is_expired': is_expired,
        'is_filled': is_filled,
        'lead_time_days': lead_time,
        'total_openings': total_openings,
        'hired_count': hired_count,
        'vacancies_remaining': max(total_openings - hired_count, 0)
    }
    # Group candidates by status
    candidates_by_status = {}
    for c in candidates:
        status = c.get('status', 'Unknown')
        if status not in candidates_by_status:
            candidates_by_status[status] = []
        candidates_by_status[status].append(c)

    # Candidate filter/view user preferences (persist in session)
    candidate_search_pref = session.get('cand_search', '')
    candidate_status_pref = session.get('cand_status', '')
    candidate_view_pref = session.get('cand_view', 'table')

    return render_template(
        'job_details.html',
        job=job,
        job_candidates=candidates,
        candidates_by_status=candidates_by_status,
        jdfile_url=jdfile_url,
        job_status_info=job_status_info,
        candidate_search_pref=candidate_search_pref,
        candidate_status_pref=candidate_status_pref,
        candidate_view_pref=candidate_view_pref,
        is_logged_in=True,
        username=current_user.username
    )
    return render_template('job_details.html', job=job, is_logged_in=True, username=current_user.username)


# Route for editing a job (stub)
@app.route('/edit_job/<job_id>', methods=['GET', 'POST'])
@login_required
def edit_job(job_id):
    # For now, just redirect back to jobs list with a flash message
    flash('Edit job feature coming soon.', 'info')
    return redirect(url_for('jobs_list'))

# Route to handle CV upload, AI match scoring, and auto-shortlisting
@app.route('/upload_cv/<job_id>', methods=['POST'])
@login_required
def upload_cv(job_id):
    file = request.files.get('cv_file')
    candidate_id = request.form.get('candidate_id')
    if not file or file.filename == '':
        flash('No CV file selected.', 'danger')
        return redirect(url_for('job_details', job_id=job_id))
    # Save CV file
    filename = secure_filename(file.filename)
    import time
    cv_filename = f"cv_{int(time.time())}_{filename}"
    cv_save_path = os.path.join('uploads', 'resumes', cv_filename)
    os.makedirs(os.path.dirname(cv_save_path), exist_ok=True)
    file.save(cv_save_path)
    # Call backend logic to analyze and update candidate
    try:
        result = analyze_cv_with_jd_and_update_candidate(
            job_id=job_id,
            candidate_id=candidate_id,
            cv_path=cv_save_path.replace('\\', '/'),
            uploaded_by=current_user.username
        )
        flash(result.get('message', 'CV uploaded and analyzed.'), 'success' if result.get('success') else 'danger')
    except Exception as e:
        flash(f'Error analyzing CV: {e}', 'danger')
    return redirect(url_for('job_details', job_id=job_id))

# Route for deleting a job (stub)
@app.route('/delete_job/<job_id>', methods=['POST', 'GET'])
@login_required
def delete_job(job_id):
    # For now, just redirect back to jobs list with a flash message
    flash('Delete job feature coming soon.', 'info')
    return redirect(url_for('jobs_list'))

from werkzeug.utils import secure_filename
import openai
import datetime

# ----------------------------------------------------------------------------------------------------------------



# Serve uploaded files (JD, CVs, etc.)
from flask import send_from_directory
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    uploads_dir = os.path.join(app.root_path, 'uploads')
    return send_from_directory(uploads_dir, filename)





# ---------------- Additional API for persisting candidate list preferences ---------------
@app.route('/set_candidate_pref', methods=['POST'])
@login_required
def set_candidate_pref():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    # Allow specific keys only
    mapping = {
        'search': 'cand_search',
        'status': 'cand_status',
        'view': 'cand_view'
    }
    for incoming, sess_key in mapping.items():
        if incoming in data:
            session[sess_key] = data[incoming]
    session.modified = True
    return jsonify(success=True, stored={k: session.get(v, '') for k, v in mapping.items()})


# ---------------- Milestones Breakup Route (Charts & Data) ----------------
@app.route('/milestones_breakup/<label>')
@login_required
def milestones_breakup(label):
    # Load data
    jobs_path = os.path.join('db', 'jobs.json')
    candidates_path = os.path.join('db', 'candidates.json')
    try:
        with open(jobs_path, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
    except Exception:
        jobs = []
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []

    # Index jobs by id for enrichment
    job_by_id = {str(j.get('job_id')): j for j in jobs}
    # Enrich candidates with department & job_title if missing
    for c in candidates:
        jid = str(c.get('job_id', ''))
        job = job_by_id.get(jid)
        if job:
            c.setdefault('department', job.get('department', 'Unknown'))
            c.setdefault('job_title', job.get('job_title', ''))

    # Basic totals
    total_applicants = len(candidates)
    total_hired = sum(1 for c in candidates if str(c.get('status', '')).lower() == 'hired')
    success_rate = int((total_hired / total_applicants) * 100) if total_applicants else 0

    # Department aggregations
    from collections import defaultdict
    dept_applicants = defaultdict(int)
    dept_hired = defaultdict(int)
    for c in candidates:
        dept = c.get('department') or 'Unknown'
        dept_applicants[dept] += 1
        if str(c.get('status', '')).lower() == 'hired':
            dept_hired[dept] += 1

    # For hiring_success_rate: success percentage per dept (avoid division by zero)
    dept_labels = sorted(dept_applicants.keys())
    if label.lower() == 'hiring_success_rate':
        dept_counts = [int((dept_hired[d] / dept_applicants[d]) * 100) if dept_applicants[d] else 0 for d in dept_labels]
    else:
        # For other pages default to applicant counts (or job counts later for vacancies)
        dept_counts = [dept_applicants[d] for d in dept_labels]

    # Vacancy stats (for total_vacancies)
    open_vacancies = 0
    closed_vacancies = 0
    for j in jobs:
        status = str(j.get('status', '')).lower()
        if status in ('open', 'active'):
            open_vacancies += 1
        elif status in ('closed', 'filled'):
            closed_vacancies += 1
    total_jobs = len(jobs)

    # Department counts for vacancies page: number of jobs per department
    if label.lower() == 'total_vacancies':
        dept_jobs = defaultdict(int)
        for j in jobs:
            dept_jobs[j.get('department', 'Unknown')] += 1
        dept_labels = sorted(dept_jobs.keys())
        dept_counts = [dept_jobs[d] for d in dept_labels]

    # Hiring pace details (simplified heuristic)
    hiring_pace_details = []
    if label.lower() == 'hiring_pace':
        now = datetime.datetime.now()
        for j in jobs:
            posted_at = j.get('posted_at')
            try:
                posted_dt = datetime.datetime.strptime(posted_at, '%Y-%m-%d %H:%M:%S') if posted_at else now
            except Exception:
                posted_dt = now
            weeks_elapsed = max(1, (now - posted_dt).days // 7 or 1)
            # Applicants for this job
            job_cands = [c for c in candidates if str(c.get('job_id')) == str(j.get('job_id'))]
            applicants_count = len(job_cands)
            hired_count_job = sum(1 for c in job_cands if str(c.get('status', '')).lower() == 'hired')
            # Derive stages_completed: simple mapping based on statuses presence
            statuses = {str(c.get('status', '')).lower() for c in job_cands}
            stage_map = [
                any(s in statuses for s in ['new', 'shortlisted', 'selected', 'approved']),  # Application
                any('interview' in s for s in statuses),                                    # Interview
                any(s in statuses for s in ['approved', 'pending-approval']),               # Approval
                any(s in statuses for s in ['hired', 'selected']),                          # Hiring
                any(s in statuses for s in ['onboarding', 'probation']),                    # Onboarding
            ]
            stages_completed = sum(1 for b in stage_map if b)
            # Pace heuristic
            if hired_count_job and weeks_elapsed <= 4:
                pace = 'Excellent'
            elif stages_completed >= 3 and weeks_elapsed <= 6:
                pace = 'Good'
            elif stages_completed >= 2:
                pace = 'Adequate'
            else:
                pace = 'Inadequate'
            hiring_pace_details.append({
                'job_title': j.get('job_title'),
                'department': j.get('department', 'Unknown'),
                'posted_at': posted_dt.strftime('%Y-%m-%d'),
                'weeks_elapsed': weeks_elapsed,
                'stages_completed': stages_completed,
                'applicants_count': applicants_count,
                'candidate_status': 'Hired' if hired_count_job else (job_cands[0].get('status') if job_cands else 'No Applicants'),
                'pace': pace,
            })

    return render_template(
        'milestones_breakup.html',
        label=label,
        total_applicants=total_applicants,
        total_hired=total_hired,
        success_rate=success_rate,
        dept_labels_json=json.dumps(dept_labels),
        dept_counts_json=json.dumps(dept_counts),
        candidates_json=json.dumps(candidates),
        open_vacancies=open_vacancies,
        closed_vacancies=closed_vacancies,
        total_jobs=total_jobs,
        hiring_pace_details=hiring_pace_details,
        is_logged_in=True,
        username=current_user.username
    )


# ---------------- Candidate Profile Route ----------------
@app.route('/candidate/<int:candidate_id>')
@login_required
def candidate_profile(candidate_id):
    candidates_path = os.path.join('db', 'candidates.json')
    jobs_path = os.path.join('db', 'jobs.json')
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []
    try:
        with open(jobs_path, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
    except Exception:
        jobs = []

    job_by_id = {str(j.get('job_id')): j for j in jobs}
    candidate = None
    for c in candidates:
        if int(c.get('id')) == candidate_id:
            # Enrich with job info if present
            job = job_by_id.get(str(c.get('job_id')))
            if job:
                c.setdefault('department', job.get('department', 'Unknown'))
                c.setdefault('job_title', job.get('job_title', ''))
            candidate = c
            break

    if not candidate:
        return render_template('candidate_profile.html', not_found=True, candidate_id=candidate_id), 404

    # Prepare status timeline (most recent first)
    history = candidate.get('status_history', []) or []
    # Sort descending by updated_at if present
    def parse_dt(dt):
        try:
            d = datetime.datetime.fromisoformat(dt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d
        except Exception:
            # Use a very old offset-aware datetime for failed parses
            return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    for h in history:
        h['_parsed_at'] = parse_dt(h.get('updated_at', ''))
    history_sorted = sorted(history, key=lambda x: x['_parsed_at'], reverse=True)

    # Build concise timeline stages for UI
    status_now = (candidate.get('status') or '').lower()
    def first_date(*keys):
        for k in keys:
            v = candidate.get(k)
            if v:
                return v
        return None
    base_defs = [
        { 'key': 'applied', 'label': 'Application Submitted', 'date': first_date('applied_date'), 'match': ['new','applied','application submitted'], 'desc': f"{candidate.get('name','Candidate')} applied" },
        { 'key': 'shortlisted', 'label': 'Shortlisted', 'date': first_date('shortlisted_date'), 'match': ['shortlisted'], 'desc': 'Resume reviewed' },
        { 'key': 'interview', 'label': 'Interview', 'date': first_date('interviewed_date','interview_date'), 'match': ['interview scheduled','interviewed'], 'desc': 'Completed' },
        { 'key': 'approval', 'label': 'Approval', 'date': first_date('selected_date'), 'match': ['selected','pending approval','approved'], 'desc': 'Approved' },
    ]
    extra_defs = []
    if any(s in status_now for s in ['hired','onboarding','probation']):
        extra_defs.append({ 'key': 'hired', 'label': 'Hired', 'date': first_date('hired_date'), 'match': ['hired'], 'desc': 'Hiring Decision' })
        extra_defs.append({ 'key': 'onboarding', 'label': 'Onboarding', 'date': first_date('onboarding_date'), 'match': ['onboarding'], 'desc': 'Onboarding Process' })
        if 'probation' in status_now or candidate.get('probation_status'):
            extra_defs.append({ 'key': 'probation', 'label': 'Probation', 'date': first_date('probation_end_date'), 'match': ['probation'], 'desc': 'Probation Period' })
    else:
        extra_defs.append({ 'key': 'offer', 'label': 'Offer Letter', 'date': None, 'match': ['offer','offer letter'], 'desc': 'Offer Stage' })
    stage_defs = base_defs + extra_defs
    current_index = 0
    for i, d in enumerate(stage_defs):
        for m in d['match']:
            if m in status_now:
                current_index = i
                break
    if status_now in ['probation']:
        current_index = len(stage_defs) - 1
    timeline_stages = []
    for i, d in enumerate(stage_defs):
        if i < current_index:
            state = 'completed'
        elif i == current_index:
            state = 'current'
        else:
            state = 'pending'
        timeline_stages.append({ 'key': d['key'], 'label': d['label'], 'date': d['date'], 'state': state, 'desc': d['desc'], 'events': [] })

    # Map history events to stages for dropdown details (using to_status)
    for ev in history:
        to_status = (ev.get('to_status') or '').lower()
        for st in timeline_stages:
            for m in stage_defs[[sd['key'] for sd in stage_defs].index(st['key'])]['match']:
                if m in to_status:
                    st['events'].append({
                        'to_status': ev.get('to_status'),
                        'from_status': ev.get('from_status'),
                        'updated_at': ev.get('updated_at'),
                        'updated_by': ev.get('updated_by'),
                        'updated_by_role': ev.get('updated_by_role'),
                        'update_type': ev.get('update_type')
                    })
                    break

    return render_template(
        'candidate_profile.html',
        candidate=candidate,
        history=history_sorted,
        timeline_stages=timeline_stages,
        is_logged_in=True,
        username=current_user.username
    )

# Signed deep-link route for Teams (optional). Provides seamless access if a valid token is supplied.
@app.route('/candidate_link/<int:candidate_id>')
def candidate_profile_link(candidate_id):
    username = request.args.get('user')
    token = request.args.get('token')
    path = f"/candidate/{candidate_id}"
    # If user already authenticated just redirect
    if current_user.is_authenticated:
        return redirect(path)
    # Validate token & auto-login user (without password) ONLY if token matches.
    if username and verify_link_token(path, username, token):
        urec = users_data.get(username)
        if urec:
            user_obj = User(urec['id'], username)
            login_user(user_obj, remember=False)
            resp = redirect(path)
            resp.set_cookie('role', urec.get('role',''), httponly=False, samesite='Lax')
            resp.set_cookie('username', username, httponly=False, samesite='Lax')
            return resp
    # Fallback: send to login with next param
    return redirect(url_for('login', next=path))


# ---------------- Candidate Status Update Route ----------------
@app.route('/update_candidate_status', methods=['POST'])
@login_required
def update_candidate_status():
    candidate_id = request.form.get('candidate_id')
    new_status = request.form.get('new_status')
    if not candidate_id or not new_status:
        flash('Missing candidate or status.', 'danger')
        return redirect(request.referrer or url_for('index'))
    candidates_path = os.path.join('db', 'candidates.json')
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []
    changed = False
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Preload jobs for department enrichment
    jobs = []
    jobs_path = os.path.join('db', 'jobs.json')
    if os.path.exists(jobs_path):
        try:
            with open(jobs_path, 'r', encoding='utf-8') as jf:
                jobs = json.load(jf)
        except Exception:
            jobs = []
    job_by_id = {str(j.get('job_id')): j for j in jobs}

    for c in candidates:
        if str(c.get('id')) == str(candidate_id):
            prev = c.get('status')
            # Normalize legacy intermediate statuses
            legacy_map = {
                'Approved': 'Selected',
                'Dept Approved': 'Selected'
            }
            if new_status in legacy_map:
                new_status = legacy_map[new_status]
            if prev in legacy_map:
                prev = legacy_map[prev]
            if prev == new_status:
                flash('Status unchanged.', 'info')
                break
            # Enrich candidate with department from job if missing
            if not c.get('department'):
                job = job_by_id.get(str(c.get('job_id')))
                if job:
                    c['department'] = job.get('department')
            c['previous_status'] = prev
            c['status'] = new_status
            c['status_updated_by'] = current_user.username
            c['status_updated_by_role'] = 'User'
            c['status_updated_at'] = now_iso
            # date field mapping
            status_date_fields = {
                'Shortlisted': 'shortlisted_date',
                'Interview Scheduled': 'interview_scheduled_date',
                'Interviewed': 'interviewed_date',
                'Selected': 'selected_date',
                'Hired': 'hired_date',
                'Onboarding': 'onboarding_date',
            }
            df = status_date_fields.get(new_status)
            if df and not c.get(df):
                c[df] = now_iso.split('T')[0]
            # timeline / progress helpers
            if new_status == 'Hired' and not c.get('onboarding_status'):
                c['onboarding_status'] = 'Pending'
            if new_status == 'Onboarding':
                c['onboarding_status'] = 'In Progress'
            if new_status == 'Probation':
                c['probation_status'] = 'In Progress'
            # append history
            hist_entry = {
                'from_status': prev,
                'to_status': new_status,
                'updated_by': current_user.username,
                'updated_by_role': 'User',
                'updated_at': now_iso,
                'update_type': 'manual_status_update'
            }
            c.setdefault('status_history', []).append(hist_entry)
            changed = True
            # --- Notification workflow triggers ---
            try:
                process_notifications_for_status_change(c, prev, new_status, current_user.username)
            except Exception as e:
                # Non-fatal
                print('Notification workflow error:', e)
            flash(f'Status updated to {new_status}.', 'success')
            break
    if changed:
        try:
            with open(candidates_path, 'w', encoding='utf-8') as f:
                json.dump(candidates, f, indent=4)
        except Exception as e:
            flash(f'Error saving status: {e}', 'danger')
    else:
        if not any(str(c.get('id')) == str(candidate_id) for c in candidates):
            flash('Candidate not found.', 'danger')
    return redirect(url_for('candidate_profile', candidate_id=candidate_id))


# ---------------- Notification Helpers ----------------
def normalize_dept(s: str):
    return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

def find_department_manager_role(job_department: str):
    target_norm = normalize_dept(job_department)
    best = None
    for uname, u in users_data.items():
        role = (u.get('role') or '')
        dept = u.get('department') or ''
        if 'department manager' in role.lower():
            if normalize_dept(dept) == target_norm:
                return role
            if not best and (dept.split()[:1] == job_department.split()[:1]):
                best = role
    return best or 'Department Manager'

def find_department_manager_user(job_department: str):
    target_norm = normalize_dept(job_department)
    fallback = None
    for uname, u in users_data.items():
        role = (u.get('role') or '')
        dept = u.get('department') or ''
        if 'department manager' in role.lower():
            if normalize_dept(dept) == target_norm:
                return uname, u
            if not fallback:
                fallback = (uname, u)
    return fallback  # may be None

def get_user_role(username: str):
    rec = users_data.get(username)
    return rec.get('role') if rec else 'User'

def load_notifications():
    path = os.path.join('db', 'notifications.json')
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_notifications(items):
    path = os.path.join('db', 'notifications.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=4)

def add_notification(candidate, notif_type, for_role, message, from_user, status='Pending', priority='normal', action_required=False):
    notes = load_notifications()
    new_id = (max([n.get('id', 0) for n in notes]) + 1) if notes else 1
    # Resolve a single receiver (optional)
    receiver_username = None
    receiver_user_id = None
    if 'department manager' in (for_role or '').lower():
        dm_user = find_department_manager_user(candidate.get('department',''))
        if dm_user:
            receiver_username = dm_user[0]
            receiver_user_id = dm_user[1].get('id')
    notes.append({
        'id': new_id,
        'candidate_id': candidate.get('id'),
        'candidate_name': candidate.get('name'),
        'position': candidate.get('position'),
        'type': notif_type,
        'status': status,
        'for_role': for_role,
        'receiver_username': receiver_username,
        'receiver_user_id': receiver_user_id,
        'from_role': get_user_role(from_user),
        'from_user': from_user,
        'message': message,
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'created_by': from_user,
        'priority': priority,
        'action_required': action_required,
        'notification_type': 'pop_up'
    })
    save_notifications(notes)
    # Fire-and-forget Teams integration
    try:
        send_teams_notification(notes[-1])
    except Exception as _e:
        pass
    try:
        print(f"[NOTIF] Created id={new_id} type={notif_type} for_role={for_role} receiver={receiver_username}")
    except Exception:
        pass

def process_notifications_for_status_change(candidate, prev_status, new_status, actor_username):
    # Determine job department via candidate (may already have department populated)
    job_department = candidate.get('department') or ''
    if not job_department:
        # attempt enrichment from jobs.json
        try:
            with open(os.path.join('db','jobs.json'), 'r', encoding='utf-8') as jf:
                jobs = json.load(jf)
            job = next((j for j in jobs if str(j.get('job_id')) == str(candidate.get('job_id'))), None)
            if job:
                job_department = job.get('department','')
                candidate['department'] = job_department
        except Exception:
            pass
    dept_manager_role = find_department_manager_role(job_department)
    cname = candidate.get('name')
    # HR Shortlists -> notify Department Manager for selection decision
    if new_status == 'Shortlisted' and prev_status != 'Shortlisted':
        add_notification(
            candidate,
            'shortlist_for_approval',
            dept_manager_role,
        f'HR SHORTLISTED: Candidate {cname} shortlisted. Department Manager to SELECT.',
            actor_username,
            action_required=True,
            priority='high'
        )
    # Department Manager selects -> status Selected -> notify Operations Manager for hire
    if new_status == 'Selected' and prev_status != 'Selected':
        add_notification(
            candidate,
            'candidate_selected',
            'Operation Manager',
        f'DEPT SELECTED: {cname} selected by Department. Operations Manager to HIRE.',
            actor_username,
            action_required=True,
            priority='high'
        )
    # Hired -> final approval complete -> notify HR and Dept Manager
    if new_status == 'Hired' and prev_status != 'Hired':
        add_notification(
            candidate,
            'final_approval_complete',
            'HR',
            f'HIRED: {cname} hired by Operations Manager.',
            actor_username,
            status='Approved',
            action_required=False,
            priority='high'
        )
        add_notification(
            candidate,
            'final_approval_complete',
            dept_manager_role,
            f'HIRED: {cname} hired. Notification sent to HR.',
            actor_username,
            status='Approved',
            action_required=False,
            priority='normal'
        )
        # Notify all Discipline Managers (same department) as well
        try:
            for uname, u in users_data.items():
                if (u.get('role','').lower() == 'discipline manager' and
                    (u.get('department') or '').lower() == (candidate.get('department') or '').lower()):
                    add_notification(
                        candidate,
                        'final_approval_complete',
                        u.get('role'),
                        f'HIRED: {cname} hired. (Discipline Manager copy)',
                        actor_username,
                        status='Approved',
                        action_required=False,
                        priority='low'
                    )
        except Exception as e:
            print('Discipline manager notify error:', e)

def recent_reminder_exists(candidate_id, notif_type, hours=REMINDER_REPEAT_HOURS):
    notes = load_notifications()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    for n in notes:
        if n.get('candidate_id') == candidate_id and n.get('type') == notif_type:
            ts = parse_iso(n.get('timestamp',''))
            if ts and ts > cutoff:
                return True
    return False

def escalate_pending(candidate, pending_status, notif_type, for_role, message):
    prev = candidate.get('status')
    if prev == pending_status:
        return False
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    candidate['previous_status'] = prev
    candidate['status'] = pending_status
    candidate['status_updated_by'] = 'system'
    candidate['status_updated_by_role'] = 'System'
    candidate['status_updated_at'] = now_iso
    candidate.setdefault('status_history', []).append({
        'from_status': prev,
        'to_status': pending_status,
        'updated_by': 'system',
        'updated_by_role': 'System',
        'updated_at': now_iso,
        'update_type': 'auto_pending_escalation'
    })
    add_notification(candidate, notif_type, for_role, message, 'system', action_required=True, priority='high')
    return True

def check_pending_reminders():
    candidates = load_candidates()
    changed = False
    now = datetime.datetime.now(datetime.timezone.utc)
    for c in candidates:
        status = c.get('status')
        # Determine last change time for current status
        last_change = None
        for ev in reversed(c.get('status_history', [])):
            if ev.get('to_status') == status:
                last_change = parse_iso(ev.get('updated_at'))
                if last_change:
                    break
        if not last_change:
            last_change = parse_iso(c.get('status_updated_at','')) or now
        hours_in_state = (now - last_change).total_seconds()/3600 if last_change else 0
        # Shortlisted waiting on Department Manager
        if status in ['Shortlisted','Pending Dept Selection'] and hours_in_state >= REMINDER_THRESHOLD_HOURS:
            if not recent_reminder_exists(c.get('id'), 'reminder_pending_dept_selection'):
                if escalate_pending(c, 'Pending Dept Selection', 'reminder_pending_dept_selection', find_department_manager_role(c.get('department','') or ''), f"REMINDER: Candidate {c.get('name')} awaiting Department Manager selection."):
                    changed = True
        # Selected waiting on Operations Manager
        if status in ['Selected','Pending Operations Hire'] and hours_in_state >= REMINDER_THRESHOLD_HOURS:
            if not recent_reminder_exists(c.get('id'), 'reminder_pending_operations_hire'):
                if escalate_pending(c, 'Pending Operations Hire', 'reminder_pending_operations_hire', 'Operation Manager', f"REMINDER: Candidate {c.get('name')} awaiting Operations Manager hire decision."):
                    changed = True
    if changed:
        save_candidates(candidates)


# ---------------- Notification API Endpoints ----------------
@app.route('/api/notifications')
@login_required
def api_get_notifications():
    """Return unread notifications for the logged-in user's role.
    Query params:
      status=All|Unread (default Unread)
      limit=int (optional)
    """
    try:
        check_pending_reminders()
    except Exception as e:
        print('Reminder check error (poll):', e)
    role = request.cookies.get('role') or get_user_role(current_user.username)
    status_filter = request.args.get('status', 'Unread')
    limit = request.args.get('limit', type=int)
    all_notifs = load_notifications()
    def base_role(r):
        return (r or '').split('(')[0].strip().lower()
    role_base = base_role(role)
    filtered = []
    auto_updated = False
    for n in all_notifs:
        fr = (n.get('for_role') or '')
        if (fr == role or role.startswith(fr) or fr.startswith(role) or
            base_role(fr) == role_base or n.get('receiver_username') == current_user.username):
            filtered.append(n)
    if status_filter != 'All':
        # Show only unread / pending action notifications. Final approval only if not yet read.
        new_list = []
        for n in filtered:
            st = n.get('status','Pending')
            if n.get('type') == 'final_approval_complete':
                if st not in ['Read','read']:
                    # auto mark read so it displays only once
                    if st in ['Approved'] and not n.get('read_at'):
                        n['status'] = 'Read'
                        n['read_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        auto_updated = True
                    new_list.append(n)
            else:
                if st not in ['Read','read','Approved','Rejected']:
                    new_list.append(n)
        filtered = new_list
    if auto_updated:
        save_notifications(all_notifs)
    # sort newest first
    filtered.sort(key=lambda n: n.get('timestamp',''), reverse=True)
    if limit:
        filtered = filtered[:limit]
    return jsonify({'role': role, 'count': len(filtered), 'notifications': filtered})


@app.route('/api/notifications/<int:notif_id>/mark_read', methods=['POST'])
@login_required
def api_mark_notification(notif_id):
    all_notifs = load_notifications()
    role = request.cookies.get('role') or get_user_role(current_user.username)
    updated = False
    def base_role(r):
        return (r or '').split('(')[0].strip().lower()
    role_base = base_role(role)
    for n in all_notifs:
        fr = (n.get('for_role') or '')
        if n.get('id') == notif_id and (fr == role or role.startswith(fr) or fr.startswith(role) or base_role(fr)==role_base or n.get('receiver_username') == current_user.username):
            n['status'] = 'Read'
            n['read_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            updated = True
            break
    if updated:
        save_notifications(all_notifs)
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Not found'}), 404

@app.route('/api/debug/all_notifications')
@login_required
def api_debug_all_notifications():
    role = request.cookies.get('role') or get_user_role(current_user.username)
    return jsonify({'current_role': role, 'all': load_notifications()})


# ---------------- Approvals Pages & Actions ----------------
@app.route('/my_approvals')
@login_required
def my_approvals():
    try:
        check_pending_reminders()
    except Exception as e:
        print('Reminder check error (approvals):', e)
    role = get_user_role(current_user.username)
    notes = load_notifications()
    # Load candidates for status reconciliation
    cand_list = load_candidates()
    cand_status = {str(c.get('id')): c.get('status') for c in cand_list}
    auto_changed = False
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Auto-complete notifications whose candidate already progressed
    for n in notes:
        if not n.get('action_required'):
            continue
        if n.get('status') in ['Approved','Rejected']:
            continue
        cid = str(n.get('candidate_id'))
        c_status = cand_status.get(cid)
        if not c_status:
            continue
        t = n.get('type')
        # Define progression sets
        if t == 'shortlist_for_approval' and c_status in ['Selected','Hired','Pending Operations Hire']:
            n['status'] = 'Approved'
            n['auto_completed_at'] = now_iso
            if not n.get('approved_by'):
                n['approved_by'] = 'System'
            auto_changed = True
        elif t == 'candidate_selected' and c_status in ['Hired']:
            n['status'] = 'Approved'
            n['auto_completed_at'] = now_iso
            if not n.get('approved_by'):
                n['approved_by'] = 'System'
            auto_changed = True
        elif t.startswith('reminder_pending_'):
            # If reminder and stage progressed beyond its pending counterpart
            if t == 'reminder_pending_dept_selection' and c_status in ['Selected','Hired','Pending Operations Hire']:
                n['status'] = 'Approved'
                n['auto_completed_at'] = now_iso
                if not n.get('approved_by'):
                    n['approved_by'] = 'System'
                auto_changed = True
            if t == 'reminder_pending_operations_hire' and c_status in ['Hired']:
                n['status'] = 'Approved'
                n['auto_completed_at'] = now_iso
                if not n.get('approved_by'):
                    n['approved_by'] = 'System'
                auto_changed = True
    if auto_changed:
        save_notifications(notes)
    def base_role(r):
        return (r or '').split('(')[0].strip().lower()
    role_base = base_role(role)
    def matches(n):
        fr = n.get('for_role','')
        return (fr == role or role.startswith(fr) or fr.startswith(role) or base_role(fr)==role_base)
    # Pending approvals: action_required and not final decision (Approved/Rejected)
    pending = [n for n in notes if matches(n) and n.get('action_required') and n.get('status') not in ['Approved','Rejected']]
    # Build decision attribution from candidate history
    history_decisions = {}
    for c in cand_list:
        cid = str(c.get('id'))
        for ev in c.get('status_history', [])[-10:]:  # recent events
            to_status = ev.get('to_status')
            if to_status in ['Shortlisted','Selected','Hired','Rejected']:
                history_decisions.setdefault(cid, []).append({
                    'status': to_status,
                    'updated_by': ev.get('updated_by'),
                    'role': ev.get('updated_by_role'),
                    'updated_at': ev.get('updated_at')
                })
    # Ensure notifications missing approved_by get it from history
    changed_hist = False
    for n in notes:
        if n.get('status') in ['Approved','Rejected'] and not n.get('approved_by'):
            cid = str(n.get('candidate_id'))
            decs = history_decisions.get(cid, [])
            # find matching status mapping
            target_status = None
            if n.get('type') == 'shortlist_for_approval':
                target_status = 'Shortlisted'
            elif n.get('type') == 'candidate_selected':
                target_status = 'Selected'
            elif n.get('type') == 'final_approval_complete':
                target_status = 'Hired'
            if target_status:
                match = next((d for d in reversed(decs) if d['status'] == target_status), None)
                if match:
                    n['approved_by'] = match['updated_by'] or 'System'
                    n['approved_at'] = match['updated_at']
                    changed_hist = True
    if changed_hist:
        save_notifications(notes)
    my_completed = [n for n in notes if matches(n) and n.get('status') in ['Approved','Rejected'] and n.get('approved_by') == current_user.username]
    other_completed = [n for n in notes if matches(n) and n.get('status') in ['Approved','Rejected'] and n.get('approved_by') != current_user.username]
    # Include informational final hire notifications (even if no approved_by) in other_completed
    # Sort
    # --- Synthesize user decisions from candidate history if notifications missing ---
    # Remove any prior synthetic entries so we can rebuild with up-to-date text
    my_completed = [n for n in my_completed if not str(n.get('id','')).startswith('synth-')]
    existing_keys = {(n.get('candidate_id'), n.get('type')) for n in my_completed}
    synth_added = False
    for c in cand_list:
        cid = c.get('id')
        for ev in c.get('status_history', [])[-25:]:
            if (ev.get('updated_by') == current_user.username and
                ev.get('to_status') in ['Shortlisted','Selected','Hired','Rejected']):
                # Map to pseudo notification type
                status = ev.get('to_status')
                current_status = c.get('status')
                name = c.get('name')
                if status == 'Shortlisted':
                    ntype = 'shortlist_for_approval'
                    if current_status == 'Shortlisted':
                        msg = f'SHORTLISTED: {name} shortlisted; awaiting Department Manager selection.'
                    elif current_status in ['Selected','Pending Operations Hire']:
                        msg = f'SHORTLISTED: {name} progressed to Selected; awaiting Operations Manager.'
                    elif current_status == 'Hired':
                        msg = f'SHORTLISTED: {name} eventually Hired (final).'
                    else:
                        msg = f'SHORTLISTED: {name} shortlisted.'
                elif status == 'Selected':
                    ntype = 'candidate_selected'
                    if current_status == 'Selected':
                        msg = f'SELECTED: {name} selected; awaiting Operations Manager hire decision.'
                    elif current_status in ['Pending Operations Hire']:
                        msg = f'SELECTED: {name} pending Operations Manager hire decision.'
                    elif current_status == 'Hired':
                        msg = f'SELECTED: {name} selected and now Hired (final).'
                    else:
                        msg = f'SELECTED: {name} selected.'
                elif status == 'Hired':
                    ntype = 'final_approval_complete'
                    msg = f'HIRED: {name} hired.'
                else:  # Rejected
                    ntype = 'candidate_rejected'
                    msg = f'REJECTED: {name} rejected.'
                key = (cid, ntype)
                if key in existing_keys:
                    continue
                # Avoid duplicating if a notification (without approved_by) already exists
                if any(n for n in my_completed if n.get('candidate_id') == cid and n.get('message') == msg):
                    continue
                my_completed.append({
                    'id': f'synth-{cid}-{ntype}',
                    'candidate_id': cid,
                    'candidate_name': c.get('name'),
                    'position': c.get('position'),
                    'type': ntype,
                    'status': 'Approved' if status != 'Rejected' else 'Rejected',
                    'for_role': role,
                    'from_role': ev.get('updated_by_role'),
                    'from_user': ev.get('updated_by'),
                    'message': msg,
                    'timestamp': ev.get('updated_at'),
                    'created_by': ev.get('updated_by'),
                    'priority': 'normal',
                    'action_required': False,
                    'notification_type': 'synthetic',
                    'approved_by': ev.get('updated_by'),
                    'approved_at': ev.get('updated_at')
                })
                synth_added = True
    if synth_added:
        # ensure synthetic decisions not also in other_completed
        other_completed = [n for n in other_completed if not str(n.get('id','')).startswith('synth-')]
    for lst in (pending, my_completed, other_completed):
        lst.sort(key=lambda n: n.get('timestamp','') or '', reverse=True)

    # ---- Build aggregated per-candidate timeline for "My Decisions" ----
    # Stages: Shortlisted (HR/Discipline) -> Selected (Department Manager) -> Hired (Operation Manager)
    my_timeline_decisions = []
    user_name = current_user.username
    for c in cand_list:
        hist = c.get('status_history', [])
        # track first occurrence of each stage
        stages_map = {
            'Shortlisted': None,
            'Selected': None,
            'Hired': None
        }
        for ev in hist:
            ts = ev.get('to_status')
            if ts in stages_map and stages_map[ts] is None:
                stages_map[ts] = {
                    'actor': ev.get('updated_by'),
                    'role': ev.get('updated_by_role'),
                    'at': ev.get('updated_at')
                }
        # Determine if user participated in any relevant stage
        participated = any(v and v.get('actor') == user_name for v in stages_map.values())
        if not participated:
            continue
        # Build ordered timeline list
        ordered = []
        for stage_label in ['Shortlisted','Selected','Hired']:
            info = stages_map[stage_label]
            completed = info is not None
            ordered.append({
                'stage': stage_label,
                'actor': info.get('actor') if info else None,
                'role': info.get('role') if info else None,
                'at': info.get('at') if info else None,
                'completed': completed,
                'is_user': info.get('actor') == user_name if info else False
            })
        # Last activity time for sorting
        last_time = None
        for st in reversed(ordered):
            if st['at']:
                last_time = st['at']
                break
        my_timeline_decisions.append({
            'candidate_id': c.get('id'),
            'candidate_name': c.get('name'),
            'position': c.get('position'),
            'current_status': c.get('status'),
            'timeline': ordered,
            'last_time': last_time
        })
    # sort aggregated list
    my_timeline_decisions.sort(key=lambda x: x.get('last_time') or '', reverse=True)
    approved_count = len(my_timeline_decisions)
    return render_template('my_approvals.html', role=role, pending_approvals=pending, completed_approvals=my_completed, other_completed_approvals=other_completed, my_timeline_decisions=my_timeline_decisions, approved_count=approved_count, is_logged_in=True, username=current_user.username)


@app.route('/approve_candidate', methods=['POST'])
@login_required
def approve_candidate():
    role = get_user_role(current_user.username)
    candidate_id = request.form.get('candidate_id')
    action = request.form.get('action')  # approve|reject
    if not candidate_id or action not in ['approve','reject']:
        flash('Invalid approval request', 'danger')
        return redirect(url_for('my_approvals'))
    # load candidates
    cand_path = os.path.join('db','candidates.json')
    try:
        with open(cand_path,'r',encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []
    candidate = next((c for c in candidates if str(c.get('id')) == str(candidate_id)), None)
    if not candidate:
        flash('Candidate not found','danger')
        return redirect(url_for('my_approvals'))
    prev_status = candidate.get('status')
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # Decide new status based on role + action
    new_status = prev_status
    # Normalize legacy statuses
    legacy_map = {
        'Approved': 'Selected',
        'Dept Approved': 'Selected'
    }
    if prev_status in legacy_map:
        prev_status = legacy_map[prev_status]
    rlow = role.lower()
    if action == 'approve':
        if any(k in rlow for k in ['hr','discipline manager','discipline']) and prev_status in ['New','Applied','Application Submitted','Pending','Review','', None]:
            new_status = 'Shortlisted'
        elif 'department manager' in rlow and prev_status in ['Shortlisted','Pending Dept Selection']:
            new_status = 'Selected'
        elif 'operation manager' in rlow and prev_status in ['Selected','Pending Operations Hire']:
            new_status = 'Hired'
    elif action == 'reject':
        new_status = 'Rejected'
    # Update candidate if status changed
    if new_status != prev_status:
        candidate['previous_status'] = prev_status
        candidate['status'] = new_status
        candidate['status_updated_by'] = current_user.username
        candidate['status_updated_by_role'] = role
        candidate['status_updated_at'] = now_iso
        candidate.setdefault('status_history', []).append({
            'from_status': prev_status,
            'to_status': new_status,
            'updated_by': current_user.username,
            'updated_by_role': role,
            'updated_at': now_iso,
            'update_type': 'approval_decision'
        })
        try:
            process_notifications_for_status_change(candidate, prev_status, new_status, current_user.username)
        except Exception as e:
            print('Approval workflow trigger error:', e)
        try:
            with open(cand_path,'w',encoding='utf-8') as f:
                json.dump(candidates,f,indent=4)
        except Exception as e:
            flash(f'Error saving candidate: {e}','danger')
    # Update notifications related to this candidate & role
    notes = load_notifications()
    changed = False
    for n in notes:
        if str(n.get('candidate_id')) == str(candidate_id) and n.get('status') not in ['Approved','Rejected'] and (n.get('for_role') == role or role.startswith(n.get('for_role','')) or n.get('for_role','').startswith(role)):
            if action == 'approve':
                # Mark the notification as Approved (notification lifecycle) but candidate status already updated above
                n['status'] = 'Approved'
            else:
                n['status'] = 'Rejected'
            n['approved_by'] = current_user.username
            n['approved_at'] = now_iso
            changed = True
    if changed:
        save_notifications(notes)
    flash(f'Candidate {action}d successfully.', 'success')
    return redirect(url_for('my_approvals'))

# ---------------- Manage Onboarding ----------------
@app.route('/manage_onboarding')
@login_required
def manage_onboarding():
    """Render the Manage Onboarding page for all hired candidates with onboarding steps."""
    candidates = []
    cand_path = os.path.join('db', 'candidates.json')
    if os.path.exists(cand_path):
        try:
            with open(cand_path, 'r', encoding='utf-8') as f:
                candidates = json.load(f)
        except Exception:
            candidates = []
    # Only hired candidates with onboarding info
    hired_candidates = [c for c in candidates if c.get('status') == 'Hired']
    return render_template(
        'manage_onboarding.html',
        candidates_list=hired_candidates,
        is_logged_in=True,
        username=current_user.username
    )
# Serve uploaded files (JD, CVs, etc.)
# ---------------- Onboarding Steps Update Route ----------------
@app.route('/update_onboarding_steps', methods=['POST'])
@login_required
def update_onboarding_steps():
    candidate_id = request.form.get('candidate_id')
    checked_steps = request.form.getlist('onboarding_steps')
    if not candidate_id:
        flash('Missing candidate.', 'danger')
        return redirect(request.referrer or url_for('index'))
    candidates_path = os.path.join('db', 'candidates.json')
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []
    changed = False
    steps = [
        'Joining Formalities',
        'HR Introduction',
        'Document Verification',
        'User Ids and ICT Allocation'
    ]
    for c in candidates:
        if str(c.get('id')) == str(candidate_id):
            c['onboarding'] = {}
            for step in steps:
                if step in checked_steps:
                    c['onboarding'][step] = 'Completed'
                else:
                    c['onboarding'][step] = 'Pending'
            changed = True
            break
    if changed:
        try:
            with open(candidates_path, 'w', encoding='utf-8') as f:
                json.dump(candidates, f, indent=4)
        except Exception:
            flash('Failed to save onboarding progress.', 'danger')
    else:
        flash('Candidate not found.', 'danger')
    return redirect(url_for('candidate_profile', candidate_id=candidate_id))





# --- Interview Video Upload & Analysis ---
from werkzeug.utils import secure_filename
import tempfile
import threading
import time

def extract_audio_from_video(video_path, audio_path):
    """Extract audio from video using moviepy."""
    try:
        from moviepy import VideoFileClip
        video = VideoFileClip(video_path)
        if not video.audio:
            print("No audio stream found in the video.")
            return False
        video.audio.write_audiofile(audio_path, fps=16000, nbytes=2, codec='pcm_s16le')
        video.close()
        return True
    except ImportError:
        print("moviepy is not installed. Install it with: pip install moviepy")
        return False
    except Exception as e:
        print(f"Audio extraction error (moviepy): {e}")
        return False

def transcribe_with_whisper(audio_path):
    try:
        with open(audio_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        return transcript
    except Exception as e:
        print(f"OpenAI Whisper API transcription error: {e}")
        return None

def analyze_transcript_with_openai(transcript):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """You are an expert interviewer analyzing candidate performance.\n\nAnalyze the interview transcript and provide:\n1. A comprehensive performance summary\n2. Specific feedback on communication skills, technical knowledge, and overall interview performance\n3. Areas for improvement\n4. A final performance score out of 100\n\nIMPORTANT: Always end your response with a clear score in this exact format: \"Performance Score: X/100\" where X is a number between 0-100."""},
                {"role": "user", "content": f"Please analyze this interview transcript and provide detailed feedback with a performance score:\n\n{transcript}"}
            ],
            temperature=0.0,
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        print(f"OpenAI summary error: {e}")
        return None

import re
def extract_performance_score(feedback_text):
    match = re.search(r"Performance Score:\s*(\d{1,3})/100", feedback_text)
    if match:
        return int(match.group(1))
    return None

def analyze_video_bg(candidate_id, round_index, video_filename, round_name=None):
    candidates_path = os.path.join('db', 'candidates.json')
    # Wait a moment to avoid race with main thread
    time.sleep(1)
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        return
    candidate = next((c for c in candidates if int(c.get('id')) == candidate_id), None)
    if not candidate:
        return
    interview_analysis = candidate.get('interview_analysis', [])
    if round_index >= len(interview_analysis):
        return
    video_full_path = os.path.join('uploads', video_filename)
    # Extract audio to temp file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_audio:
        audio_path = tmp_audio.name
    audio_success = extract_audio_from_video(video_full_path, audio_path)
    transcript = None
    feedback = None
    score = None
    if audio_success:
        transcript = transcribe_with_whisper(audio_path)
        if transcript:
            feedback = analyze_transcript_with_openai(transcript)
            score = extract_performance_score(feedback) if feedback else None
    try:
        os.remove(audio_path)
    except Exception:
        pass
    # Update analysis result
    interview_analysis[round_index]['transcript'] = transcript
    interview_analysis[round_index]['feedback'] = feedback
    interview_analysis[round_index]['performance_score'] = score
    interview_analysis[round_index]['processing'] = False
    if round_name is not None:
        interview_analysis[round_index]['round_name'] = round_name
    # Save back (thread-safe)
    for _ in range(5):
        try:
            with open(candidates_path, 'r', encoding='utf-8') as f:
                candidates = json.load(f)
            candidate = next((c for c in candidates if int(c.get('id')) == candidate_id), None)
            if not candidate:
                return
            candidate['interview_analysis'] = interview_analysis
            with open(candidates_path, 'w', encoding='utf-8') as f:
                json.dump(candidates, f, indent=4)
            break
        except Exception:
            time.sleep(0.5)

@app.route('/upload_interview_videos/<int:candidate_id>', methods=['POST'])
@login_required
def upload_interview_videos(candidate_id):
    candidates_path = os.path.join('db', 'candidates.json')
    try:
        with open(candidates_path, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
    except Exception:
        candidates = []
    candidate = next((c for c in candidates if int(c.get('id')) == candidate_id), None)
    if not candidate:
        flash('Candidate not found.', 'danger')
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))


    files = request.files.getlist('interview_videos')
    round_names = request.form.getlist('round_names')
    if not files or len(files) == 0:
        flash('No interview videos uploaded.', 'danger')
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))

    interview_analysis = candidate.get('interview_analysis', [])
    for idx, file in enumerate(files):
        if not file or file.filename == '':
            continue
        filename = secure_filename(f"candidate{candidate_id}_round{len(interview_analysis)+1}_" + file.filename)
        video_save_path = os.path.join('uploads', 'interview_videos')
        os.makedirs(video_save_path, exist_ok=True)
        video_full_path = os.path.join(video_save_path, filename)
        file.save(video_full_path)
        round_name = round_names[idx] if idx < len(round_names) else f"Round {len(interview_analysis)+1}"
        # Mark as processing
        interview_analysis.append({
            'video_filename': f"interview_videos/{filename}",
            'transcript': None,
            'feedback': None,
            'performance_score': None,
            'processing': True,
            'round_name': round_name
        })
    candidate['interview_analysis'] = interview_analysis
    # Save back
    try:
        with open(candidates_path, 'w', encoding='utf-8') as f:
            json.dump(candidates, f, indent=4)
    except Exception as e:
        flash(f'Error saving analysis: {e}', 'danger')
        return redirect(url_for('candidate_profile', candidate_id=candidate_id))
    # Start background threads for new videos
    start_idx = len(interview_analysis) - len(files)
    for i in range(len(files)):
        round_name = round_names[i] if i < len(round_names) else f"Round {start_idx + i + 1}"
        t = threading.Thread(target=analyze_video_bg, args=(candidate_id, start_idx + i, interview_analysis[start_idx + i]['video_filename'], round_name))
        t.daemon = True
        t.start()
    flash('Interview videos uploaded. Analysis will complete in background.', 'success')
    return redirect(url_for('candidate_profile', candidate_id=candidate_id))












if __name__ == '__main__':
    app.run(debug=True , port= 5000 , host='0.0.0.0')
