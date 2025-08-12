from dotenv import load_dotenv  
import openai
import docx
import PyPDF2
import os
import json
import re
import datetime
from collections import defaultdict

# Ensure .env is loaded early
load_dotenv(override=True)
def extract_text_from_file(file_path):
	ext = file_path.split('.')[-1].lower()
	if ext == 'pdf':
		with open(file_path, 'rb') as f:
			reader = PyPDF2.PdfReader(f)
			return '\n'.join(page.extract_text() or '' for page in reader.pages)
	elif ext in ['doc', 'docx']:
		doc = docx.Document(file_path)
		return '\n'.join([p.text for p in doc.paragraphs])
	else:
		with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
			return f.read()

def call_openai_match_score(jd_text, cv_text):
	"""Return an integer 0-100 match score using ChatCompletion; robust fallback if API fails."""
	openai.api_key = os.getenv("OPENAI_API_KEY")
	# Trim overly long CV/JD to keep tokens reasonable
	max_len = 6000
	jd_trim = jd_text[:max_len]
	cv_trim = cv_text[:max_len]
	prompt = f"You are an expert technical recruiter. Rate the candidate CV against the JD with a single integer 0-100 (higher is better) then a hyphen and a very short reason.\nJD:\n{jd_trim}\n\nCV:\n{cv_trim}\n\nFormat: <number>-<reason>"
	model_candidates = ["gpt-4", "gpt-3.5-turbo", "gpt-3.5-turbo-instruct"]  # Compatible with openai==0.28.0
	for model in model_candidates:
		try:
			if 'instruct' in model:  # use Completion endpoint
				resp = openai.Completion.create(engine=model, prompt=prompt, max_tokens=32, temperature=0.2)
				text = resp.choices[0].text.strip()
			else:
				resp = openai.ChatCompletion.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=32, temperature=0.2)
				text = resp.choices[0].message.content.strip()
			# Extract first integer
			import re as _re
			m = _re.search(r"(100|\b\d{1,2}\b)", text)
			if m:
				val = int(m.group(1))
				return max(0, min(100, val))
		except Exception:
			continue
	return 0


def extract_candidate_data_from_cv(cv_text):
	"""
	Extracts candidate fields from CV text using OpenAI, with regex fallback for key fields.
	Fields: name, email, phone, skills, experience, education, certifications, projects, linkedin, github
	"""
	import json as _pyjson
	openai.api_key = os.environ.get('OPENAI_API_KEY')
	debug = {"openai_used": False}

	# Prepare OpenAI prompt (truncate to keep within token limits for older models)
	max_len = 8000
	trimmed = cv_text[:max_len]
	prompt = f"""Extract structured candidate info from the CV below in strict JSON only. Fields: name (string), email (string), phone (string), skills (array of strings), experience (array of role/company strings), education (array), certifications (array), projects (array), linkedin (string), github (string). Use empty string/list if missing. Do NOT include keys outside this set.\nCV:\n{trimmed}\nJSON:"""

	extracted = {k: ([] if k in ['skills','experience','education','certifications','projects'] else '') for k in ["name","email","phone","skills","experience","education","certifications","projects","linkedin","github"]}

	model_candidates = ["gpt-4", "gpt-3.5-turbo"]
	for model in model_candidates:
		try:
			resp = openai.ChatCompletion.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=700, temperature=0)
			text = resp.choices[0].message.content.strip()
			debug['raw_response'] = text
			data = _pyjson.loads(text)
			for k in extracted:
				if k in data and isinstance(data[k], type(extracted[k])):
					extracted[k] = data[k]
			debug['openai_used'] = True
			break
		except Exception as e:
			debug.setdefault('openai_errors', []).append({model: str(e)})

	# ---------------- Fallback Heuristics ----------------
	def grab_section(section_names):
		pattern = re.compile(r"^(?:" + "|".join([re.escape(s) for s in section_names]) + r")[\s:]*$", re.IGNORECASE)
		lines = [l.rstrip() for l in cv_text.splitlines()]
		collected = []
		capture = False
		for line in lines:
			if pattern.match(line.strip()):
				capture = True
				continue
			if capture and (line.strip().isupper() and len(line.split()) <= 5 and len(line) < 40):
				# Next header (all caps short line)
				break
			if capture:
				if line.strip():
					collected.append(line.strip())
		return collected

	# Email & phone
	if not extracted['email']:
		m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cv_text)
		if m:
			extracted['email'] = m.group(0); debug['regex_email'] = extracted['email']
	if not extracted['phone']:
		m = re.search(r"(\+?\d[\d\s\-()]{7,})", cv_text)
		if m:
			extracted['phone'] = m.group(0); debug['regex_phone'] = extracted['phone']

	# Name heuristic (first non-empty top line without certain keywords)
	if not extracted['name']:
		for line in cv_text.splitlines()[:12]:
			l = line.strip()
			if l and len(l.split()) <= 6 and len(l.split()) >= 2 and not any(x in l.lower() for x in ['curriculum','resume','cv','email','phone','@']):
				extracted['name'] = l; debug['regex_name'] = l; break

	# Skills
	if not extracted['skills']:
		sec = grab_section(['SKILLS','TECHNICAL SKILLS','CORE SKILLS','KEY SKILLS'])
		if sec:
			# Split by commas or semicolons
			parts = re.split(r",|;|\u2022|\|", ' '.join(sec))
			skills = sorted({p.strip() for p in parts if 1 < len(p.strip()) <= 50})
			if skills:
				extracted['skills'] = skills; debug['skills_fallback'] = True
	# Experience
	if not extracted['experience']:
		sec = grab_section(['EXPERIENCE','WORK EXPERIENCE','PROFESSIONAL EXPERIENCE'])
		if sec:
			extracted['experience'] = [l for l in sec if len(l) > 4][:25]; debug['experience_fallback'] = True
	# Education
	if not extracted['education']:
		sec = grab_section(['EDUCATION','ACADEMIC QUALIFICATIONS','ACADEMICS'])
		if sec:
			extracted['education'] = [l for l in sec if len(l) > 4][:15]; debug['education_fallback'] = True
	# Certifications
	if not extracted['certifications']:
		sec = grab_section(['CERTIFICATIONS','CERTIFICATES','LICENSES'])
		if sec:
			extracted['certifications'] = [l for l in sec if len(l) > 2][:20]; debug['certifications_fallback'] = True
	# Projects
	if not extracted['projects']:
		sec = grab_section(['PROJECTS','PROJECT EXPERIENCE'])
		if sec:
			extracted['projects'] = [l for l in sec if len(l) > 2][:20]; debug['projects_fallback'] = True

	# LinkedIn & GitHub
	if not extracted['linkedin']:
		m = re.search(r"https?://(?:www\.)?linkedin\.com/[A-Za-z0-9_\-/]+", cv_text, re.IGNORECASE)
		if m:
			extracted['linkedin'] = m.group(0); debug['linkedin_regex'] = True
	if not extracted['github']:
		m = re.search(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_\-]+", cv_text, re.IGNORECASE)
		if m:
			extracted['github'] = m.group(0); debug['github_regex'] = True

	# Simple keyword-based skill enrichment if still small
	if len(extracted['skills']) < 3:
		common_skills = ['python','java','c++','sql','excel','power bi','autocad','sp3d','smartplant','instrumentation','electrical','piping']
		found = []
		low = cv_text.lower()
		for kw in common_skills:
			if kw in low:
				found.append(kw.title())
		if found:
			merged = list(dict.fromkeys(extracted['skills'] + found))
			extracted['skills'] = merged
			debug['skills_enriched'] = True

	return extracted, debug




def analyze_cv_with_jd_and_update_candidate(job_id, candidate_id, cv_path, uploaded_by):
	# Load jobs
	jobs_path = os.path.join('db', 'jobs.json')
	with open(jobs_path, 'r', encoding='utf-8') as f:
		jobs = json.load(f)
	job = next((j for j in jobs if str(j.get('job_id')) == str(job_id)), None)
	if not job:
		return {'success': False, 'message': 'Job not found.'}
	jd_file_path = job.get('jd_file_path')
	if not jd_file_path or not os.path.exists(jd_file_path):
		return {'success': False, 'message': 'JD file not found.'}
	jd_text = extract_text_from_file(jd_file_path)
	cv_text = extract_text_from_file(cv_path)
	# Extract all candidate data from CV
	extracted, debug_extract = extract_candidate_data_from_cv(cv_text)
	debug_extract['cv_text'] = cv_text[:1000]
	# Call OpenAI for match score
	match_score = call_openai_match_score(jd_text, cv_text)
	if match_score is None:
		match_score = 0
	# Load candidates
	candidates_path = os.path.join('db', 'candidates.json')
	with open(candidates_path, 'r', encoding='utf-8') as f:
		candidates = json.load(f)
	# Find candidate by id or email (if new, add)
	candidate = None
	for c in candidates:
		if (candidate_id and str(c.get('id')) == str(candidate_id)) or (extracted['email'] and c.get('email') == extracted['email']):
			candidate = c
			break
	if not candidate:
		# New candidate
		new_id = max([c.get('id', 0) for c in candidates] + [0]) + 1
		candidate = {
			'id': new_id,
			'job_id': job_id,
			'cv_path': cv_path,
			'status': 'New',
			'applied_date': datetime.datetime.now().strftime('%Y-%m-%d'),
			'match_score': match_score,
			'status_history': [],
			'debug_extract': debug_extract,
			**extracted
		}
		candidates.append(candidate)
	else:
		candidate['cv_path'] = cv_path
		candidate['match_score'] = match_score
		candidate['debug_extract'] = debug_extract
		for k, v in extracted.items():
			candidate[k] = v
	# Auto-shortlisting logic
	auto_shortlisting = job.get('auto_shortlisting', False)
	threshold = int(job.get('match_score', 75))
	if auto_shortlisting and match_score >= threshold:
		prev_status = candidate.get('status', 'New')
		candidate['status'] = 'Shortlisted'
		candidate.setdefault('status_history', []).append({
			'from_status': prev_status,
			'to_status': 'Shortlisted',
			'updated_by': uploaded_by,
			'updated_by_role': 'Automated (AI Shortlisting)',
			'updated_at': datetime.datetime.now().isoformat(),
			'update_type': 'auto_shortlisting',
		})
	# Save candidates
	with open(candidates_path, 'w', encoding='utf-8') as f:
		json.dump(candidates, f, indent=4)
	return {'success': True, 'message': f'CV analyzed. Match score: {match_score}%.', 'match_score': match_score, 'debug_extract': debug_extract, **extracted}
def save_job_post(form, file_storage, posted_by, auto_shortlisting=False, match_score=75):
	# Prepare job data
	jobs_path = os.path.join('db', 'jobs.json')
	with open(jobs_path, 'r') as f:
		jobs = json.load(f)
	# Generate new job_id
	job_id = str(max([int(j['job_id']) for j in jobs] + [0]) + 1)
	# Save JD file
	jd_file = file_storage
	jd_filename = f"jd_{job_id}_{int(datetime.datetime.now().timestamp())}.{jd_file.filename.split('.')[-1]}"
	jd_save_path = os.path.join('uploads', 'jd_files', jd_filename)
	os.makedirs(os.path.dirname(jd_save_path), exist_ok=True)
	jd_file.save(jd_save_path)
	# Build job dict
	job = {
		'job_id': job_id,
		'job_title': form['job_title'],
		'job_description': '',
		'job_location': form['job_location'],
		'job_type': form['job_type'],
		'job_requirements': form['job_requirements'],
		'job_openings': form['job_openings'],
		'job_posted_by': posted_by,
		'job_lead_time': form['lead_time'],
		'department': form['department'],
		'seniority_level': form['seniority_level'],
		'salary_range': form['salary_range'],
		'jd_file_path': jd_save_path.replace('\\', '/'),
		'posted_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		'status': 'Open',
		'auto_shortlisting': auto_shortlisting,
		'match_score': match_score
	}
	jobs.append(job)
	with open(jobs_path, 'w') as f:
		json.dump(jobs, f, indent=2)
	return job

# (Imports moved to top; kept for backward compatibility with existing references)

def get_dashboard_data():
	# Load candidates and jobs
	with open(os.path.join('db', 'candidates.json'), 'r') as f:
		candidates = json.load(f)
	with open(os.path.join('db', 'jobs.json'), 'r') as f:
		jobs = json.load(f)

	# Metrics
	total_applicants = len(candidates)
	total_vacancies = sum(int(j.get('job_openings', 0)) for j in jobs)
	total_hired = sum(1 for c in candidates if c.get('status', '').lower() == 'hired')
	hiring_success_rate = int((total_hired / total_applicants) * 100) if total_applicants else 0
	hiring_pace = 'Good' if hiring_success_rate > 70 else ('Adequate' if hiring_success_rate > 40 else 'Inadequate')

	# Time series for charts
	def get_period(date_str, period_type):
		dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
		if period_type == 'month':
			return dt.strftime('%Y-%m')
		elif period_type == 'week':
			return dt.strftime('%Y-W%U')
		else:
			return dt.strftime('%Y-%m-%d')

	periods = {'month': set(), 'week': set(), 'day': set()}
	applicants_by_period = defaultdict(lambda: defaultdict(int))
	hired_by_period = defaultdict(lambda: defaultdict(int))
	vacancies_by_period = defaultdict(lambda: defaultdict(int))

	for c in candidates:
		for period_type in ['month', 'week', 'day']:
			period = get_period(c.get('applied_date', '2025-01-01'), period_type)
			periods[period_type].add(period)
			applicants_by_period[period_type][period] += 1
			if c.get('status', '').lower() == 'hired':
				hired_by_period[period_type][period] += 1

	for j in jobs:
		posted_at = j.get('posted_at', '').split(' ')[0]
		for period_type in ['month', 'week', 'day']:
			period = get_period(posted_at, period_type)
			periods[period_type].add(period)
			vacancies_by_period[period_type][period] += int(j.get('job_openings', 0))

	# Sort periods
	sorted_periods = {k: sorted(list(v)) for k, v in periods.items()}

	# Prepare chart data
	def get_chart_data(data_dict, period_type):
		return [data_dict[period_type].get(p, 0) for p in sorted_periods[period_type]]

	vacancy_hired_labels = {k: v for k, v in sorted_periods.items()}
	overall_vacancies_data = {k: get_chart_data(vacancies_by_period, k) for k in ['month', 'week', 'day']}
	overall_hired_data = {k: get_chart_data(hired_by_period, k) for k in ['month', 'week', 'day']}
	overall_applicants_data = {k: get_chart_data(applicants_by_period, k) for k in ['month', 'week', 'day']}

	# For demo, active = last 30 days
	cutoff = (datetime.datetime.now() - datetime.timedelta(days=30)).date()
	active_applicants_by_period = defaultdict(lambda: defaultdict(int))
	active_hired_by_period = defaultdict(lambda: defaultdict(int))
	active_vacancies_by_period = defaultdict(lambda: defaultdict(int))
	active_periods = {'month': set(), 'week': set(), 'day': set()}
	for c in candidates:
		applied_date = c.get('applied_date', '2025-01-01')
		dt = datetime.datetime.strptime(applied_date, '%Y-%m-%d').date()
		if dt >= cutoff:
			for period_type in ['month', 'week', 'day']:
				period = get_period(applied_date, period_type)
				active_periods[period_type].add(period)
				active_applicants_by_period[period_type][period] += 1
				if c.get('status', '').lower() == 'hired':
					active_hired_by_period[period_type][period] += 1
	for j in jobs:
		posted_at = j.get('posted_at', '').split(' ')[0]
		dt = datetime.datetime.strptime(posted_at, '%Y-%m-%d').date()
		if dt >= cutoff:
			for period_type in ['month', 'week', 'day']:
				period = get_period(posted_at, period_type)
				active_periods[period_type].add(period)
				active_vacancies_by_period[period_type][period] += int(j.get('job_openings', 0))
	active_sorted_periods = {k: sorted(list(v)) for k, v in active_periods.items()}
	def get_active_chart_data(data_dict, period_type):
		return [data_dict[period_type].get(p, 0) for p in active_sorted_periods[period_type]]
	active_vacancies_data = {k: get_active_chart_data(active_vacancies_by_period, k) for k in ['month', 'week', 'day']}
	active_hired_data = {k: get_active_chart_data(active_hired_by_period, k) for k in ['month', 'week', 'day']}
	active_applicants_data = {k: get_active_chart_data(active_applicants_by_period, k) for k in ['month', 'week', 'day']}

	return {
		'total_applicants': total_applicants,
		'total_vacancies': total_vacancies,
		'total_hired': total_hired,
		'hiring_success_rate': hiring_success_rate,
		'hiring_pace': hiring_pace,
		'vacancy_hired_labels_json': json.dumps(vacancy_hired_labels),
		'overall_vacancies_data_json': json.dumps(overall_vacancies_data),
		'overall_hired_data_json': json.dumps(overall_hired_data),
		'overall_applicants_data_json': json.dumps(overall_applicants_data),
		'active_vacancies_data_json': json.dumps(active_vacancies_data),
		'active_hired_data_json': json.dumps(active_hired_data),
		'active_applicants_data_json': json.dumps(active_applicants_data),
	}
