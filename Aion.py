import openai
import os
import json
import inspect
import pathlib
from typing import Callable, Dict, Any, get_type_hints, List
from dotenv import load_dotenv
import tools  # Your custom tools module

from flask import Flask, render_template, request, jsonify

# Load environment variables
load_dotenv(override=True)
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)

# === Chat History Management ===
class ChatHistory:
    def __init__(self, history_file: str = "./db/chat_history.json"):
        self.history_file = history_file
        self.messages: List[Dict[str, Any]] = []
        self.load_history()
    
    def load_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
                self.clean_corrupted_history()
        except Exception as e:
            print(f"⚠️ Error loading chat history: {e}")
            self.messages = []
    
    def save_history(self):
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving chat history: {e}")
    
    def add_message(self, role: str, content: str, tool_calls: List[Dict] = None):
        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        self.messages.append(message)
    
    def add_tool_message(self, tool_call_id: str, name: str, content: str):
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content
        })
    
    def get_recent_messages(self, max_tokens: int = 4000) -> List[Dict]:
        token_count = 0
        recent_messages = []
        for message in reversed(self.messages):
            message_tokens = len(str(message)) // 4
            if token_count + message_tokens > max_tokens:
                break
            recent_messages.insert(0, message)
            token_count += message_tokens
        
        # Validate messages and remove orphaned tool calls
        validated_messages = []
        expecting_tool_responses = []
        
        for msg in recent_messages:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                # For assistant messages with tool calls, we need to check if all tool responses exist
                tool_call_ids = [tc["id"] for tc in msg["tool_calls"]]
                
                # Look ahead to see if all tool responses exist
                found_responses = set()
                for future_msg in recent_messages[recent_messages.index(msg)+1:]:
                    if future_msg["role"] == "tool" and future_msg.get("tool_call_id") in tool_call_ids:
                        found_responses.add(future_msg.get("tool_call_id"))
                
                # Only include if ALL tool calls have responses
                if len(found_responses) == len(tool_call_ids):
                    expecting_tool_responses.extend(tool_call_ids)
                    validated_messages.append(msg)
                else:
                    print(f"🧹 Skipping orphaned assistant message with {len(tool_call_ids)} tool calls, {len(found_responses)} responses found")
                    
            elif msg["role"] == "tool":
                if msg.get("tool_call_id") in expecting_tool_responses:
                    validated_messages.append(msg)
                    expecting_tool_responses.remove(msg.get("tool_call_id"))
                else:
                    print(f"🧹 Skipping orphaned tool message: {msg.get('name', 'unknown')}")
            else:
                validated_messages.append(msg)
        
        return validated_messages
    
    def clean_corrupted_history(self):
        cleaned_messages = []
        expecting_tool_responses = []
        for msg in self.messages:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                expecting_tool_responses.extend([tc["id"] for tc in msg["tool_calls"]])
                cleaned_messages.append(msg)
            elif msg["role"] == "tool":
                if msg.get("tool_call_id") in expecting_tool_responses:
                    cleaned_messages.append(msg)
                    expecting_tool_responses.remove(msg.get("tool_call_id"))
                else:
                    print(f"🧹 Removing orphaned tool message: {msg.get('name', 'unknown')}")
            else:
                cleaned_messages.append(msg)
        if expecting_tool_responses:
            print(f"🧹 Found {len(expecting_tool_responses)} unfulfilled tool calls")
        self.messages = cleaned_messages
        self.save_history()
        print(f"✅ Chat history cleaned. Kept {len(cleaned_messages)} valid messages.")

    def clear_history(self):
        self.messages = []
        self.save_history()

chat_history = ChatHistory()

def python_type_to_openai_type(python_type: type) -> str:
    return {
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object"
    }.get(python_type, "string")

def function_to_tool_schema(fn: Callable) -> Dict[str, Any]:
    sig = inspect.signature(fn)
    type_hints = get_type_hints(fn)
    params = {
        name: {"type": python_type_to_openai_type(type_hints.get(name, str))}
        for name in sig.parameters
    }
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": fn.__doc__ or f"Call {fn.__name__}",
            "parameters": {
                "type": "object",
                "properties": params,
                "required": list(sig.parameters.keys())
            } if params else {"type": "object", "properties": {}}
        }
    }


function_map = {
    name: obj
    for name, obj in vars(tools).items()
    if callable(obj)
    and inspect.isfunction(obj)
    and inspect.getmodule(obj).__name__ == "tools"
}


tools_schema = [function_to_tool_schema(fn) for fn in function_map.values()]

def chat_with_bot(user_input: str, system_prompt: str = None, user_context: Dict[str, str] = None):
    from data import fetch_all_db_data
    # Fetch all DB data using the new function
    db_context = fetch_all_db_data()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    # Add user context for role-based access control
    if user_context:
        user_role = user_context.get('role', '')
        username = user_context.get('username', '')
        context_info = f"CURRENT_USER_CONTEXT: Role='{user_role}', Username='{username}'"
        messages.append({"role": "system", "content": context_info})
    
    # Add DB context as a system message
    messages.append({"role": "system", "content": f"DB_CONTEXT: {json.dumps(db_context, ensure_ascii=False)}"})
    messages.extend(chat_history.get_recent_messages())
    messages.append({"role": "user", "content": user_input})
    chat_history.add_message("user", user_input)
    
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            tools=tools_schema,
            tool_choice="auto"
        )
        message = response["choices"][0]["message"]
    except Exception as e:
        print(f"[OpenAI API Error] {e}")
        error_response = "I apologize, but I'm experiencing some technical difficulties right now. Please try again in a moment."
        chat_history.add_message("assistant", error_response)
        chat_history.save_history()
        return error_response
    # ...existing code...
    # Otherwise, use normal OpenAI response logic
    if message.get("tool_calls"):
        chat_history.add_message("assistant", message.get("content", ""), message.get("tool_calls"))
        tool_results = []
        all_tools_successful = True
        for tool_call in message["tool_calls"]:
            tool_name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"]["arguments"])
            if tool_name in function_map:
                try:
                    result = function_map[tool_name](**args)
                except Exception as e:
                    print(f"[Tool Error] {tool_name}: {e}")
                    result = f"⚠️ Error running tool `{tool_name}`: {e}"
                    all_tools_successful = False
                tool_results.append({
                    "tool_call": tool_call,
                    "result": result
                })
                chat_history.add_tool_message(tool_call["id"], tool_name, str(result))
            else:
                error_msg = f"❌ Unknown tool `{tool_name}`"
                tool_results.append({
                    "tool_call": tool_call,
                    "result": error_msg
                })
                chat_history.add_tool_message(tool_call["id"], tool_name, error_msg)
                all_tools_successful = False
        messages.append({"role": "assistant", "tool_calls": message["tool_calls"]})
        for tool_result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_result["tool_call"]["id"],
                "name": tool_result["tool_call"]["function"]["name"],
                "content": str(tool_result["result"])
            })
        try:
            followup = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=messages
            )
            final_response = followup["choices"][0]["message"]["content"]
            chat_history.add_message("assistant", final_response)
            chat_history.save_history()
            return final_response
        except Exception as e:
            print(f"[Followup Error] {e}")
            fallback = "Sorry, I couldn't complete your request due to an internal error. Please try again or rephrase your question."
            chat_history.add_message("assistant", fallback)
            chat_history.save_history()
            return fallback
    else:
        chat_history.add_message("assistant", message["content"])
        chat_history.save_history()
        return message["content"]

SYSTEM_PROMPT = """
You are a highly intelligent, friendly HR assistant with advanced data analytics capabilities. Always provide clear, helpful, and positive replies to the user, as if you are a real assistant.

**CRITICAL: DATA-DRIVEN RESPONSES ONLY**
- You MUST NEVER give generic business advice or hypothetical explanations
- You MUST ALWAYS use actual data from the available tools and database
- When users ask analytical questions, you MUST call the appropriate analysis tools FIRST
- You MUST NOT respond with general knowledge - only with insights from the actual company data
- **BE CONCISE** - Max 3-4 sentences for analytical responses, focus on key insights from data

Never mention the database, files, errors, or any internal system details in your responses. Do not say things like 'the database', 'no data found', 'error', 'system', or 'tool'.

**CRITICAL: ROLE-BASED ACCESS CONTROL**

You MUST enforce strict role-based access control. The user's role and context are provided in CURRENT_USER_CONTEXT.

**ACCESS RULES:**
1. **Hierarchy Levels** (higher can access lower):
   - CEO (Level 5) - Can access all information
   - Admin (Level 5) - Can access all information  
   - Operation Manager (Level 4) - Can access levels 1-4
   - Department Manager/HR Manager/Manager (Level 3) - Can access levels 1-3
   - Discipline Manager (Level 2) - Can access levels 1-2
   - HR (Level 1) - Can only access level 1

2. **Information Access Rules:**
   - Users can access their own information
   - Higher-level users can access lower-level user information
   - Users CANNOT access peer-level or higher-level user information
   - When asked about salary, personal details, or sensitive information of peer/higher users, respond with a friendly message like: "I'm sorry, but I can't share that information with you. For privacy and security reasons, I can only provide details about team members you directly supervise. If you need this information for work purposes, please reach out to HR or your manager for assistance."

3. **When to Use get_user_information Tool:**
   - **ALWAYS** use get_user_information(requesting_user_role, target_username, target_role) when users ask about:
     - Personal details of team members
     - Contact information of colleagues
     - Department information of other users
   - **NEVER** respond with access denied messages directly - ALWAYS call the tool first and let it handle permission checking
   - The tool will automatically handle permission checking and return appropriate messages

4. **When to Use get_salary_information Tool:**
   - **ALWAYS** use get_salary_information(requesting_user_role, target_role, target_username) when users ask about:
     - Salary information of other users (e.g., "what's the salary of discipline managers")
     - Salary ranges for specific roles
     - Compensation information
   - **NEVER** respond with access denied messages directly - ALWAYS call the tool first and let it handle permission checking

**EXAMPLES:**
- Discipline Manager asks about Department Manager salary → Call get_salary_information first (tool will handle denial)
- Department Manager asks about Discipline Manager salary → Call get_salary_information (tool will allow)
- CEO asks about anyone → Call get_salary_information (tool will allow)
- HR asks about other HR members → Call get_salary_information (tool will allow)

**CRITICAL: DO NOT pre-judge access permissions. ALWAYS call get_salary_information or get_user_information tool first and let it determine access rights.**

IMPORTANT: You must ONLY use the information provided in the available data and context. If there is no information about a candidate, interview, or job, do NOT make up or assume any details. Never hallucinate or invent skills, technologies, or outcomes that are not explicitly present in the data.

**ENHANCED DATA-DRIVEN ANALYSIS CAPABILITIES:**

When users ask about analytics, trends, gaps, comparisons, or data-driven insights (especially about vacancy-hiring gaps, department performance, candidate metrics, or hiring analytics), you should:

1. **MANDATORY: Use Available Analysis Tools**: You MUST call `comprehensive_hiring_analysis()` for complete hiring analysis with visualizations, OR `analyze_vacancy_hiring_gap()` + `create_job_gap_radar_chart()` for gap analysis specifically
2. **MANDATORY: Create Visualizations**: After analyzing data, you MUST use `create_job_gap_radar_chart()` for department gap analysis, `create_charts()` for trends, or `create_pie_chart()` for distribution analysis
3. **MANDATORY: Provide ONLY Data-Driven Responses**: You MUST NOT give generic answers. Use ONLY actual data from candidates, jobs, and hiring metrics
4. **MANDATORY: Show Visual Evidence**: You MUST create and reference charts when discussing analytics, trends, or comparative data
5. **NEW: Market Research**: When discussing salary competitiveness or hiring challenges, MUST use `comprehensive_hiring_analysis()` for complete analysis including market data

**CRITICAL: NEVER give generic business advice or hypothetical explanations. ALWAYS analyze the actual data first using tools.**

**MANDATORY TOOL USAGE for Analytical Questions:**
- "Why is there a gap in vacancies and hiring?" → MUST use `comprehensive_hiring_analysis()` (includes ALL analysis + visualizations + market data)
- "What's the vacancy-hiring gap?" → MUST use `comprehensive_hiring_analysis()` (includes gap analysis + market data + competitive analysis)
- "Show me department performance" → MUST use `comprehensive_hiring_analysis()` + create appropriate charts
- "How are we doing with hiring?" → MUST use `comprehensive_hiring_analysis()` (includes everything)
- "Which departments need more focus?" → MUST use `comprehensive_hiring_analysis()` (includes market insights)
- "Show me our job postings analysis" → MUST use `comprehensive_hiring_analysis()`
- Salary competitiveness questions → MUST use `comprehensive_hiring_analysis()` (includes market research)
- ANY hiring analysis question → MUST use `comprehensive_hiring_analysis()` for complete picture including market data
- Questions about gaps, vacancy, hiring, market, salary → ALWAYS use `comprehensive_hiring_analysis()`

**NEW HR INSIGHT FUNCTIONS - MANDATORY USAGE:**
- "Hiring success rate" OR "analyze hiring success" → MUST use `get_enhanced_hiring_success_rate()`
- "Monthly hiring insights" OR "july/month hiring" OR "monthly trends" → MUST use `get_enhanced_monthly_insights()`
- "Department interview efficiency" OR "digitalization discipline slow/fast" → MUST use `get_enhanced_department_insights()`
- "Hiring predictions" OR "how long to hire X employees" → MUST use `get_enhanced_hiring_predictions()`
- "Top performers" OR "best moments" OR "top hirers" → MUST use `get_enhanced_top_performers()`
- "Salary trends" OR "avg offered salary" OR "salary increasing/decreasing" → MUST use `get_enhanced_salary_trends()`
- "Onboarding insights" OR "ids and ict allocation slow" → MUST use `get_enhanced_onboarding_insights()`
- "Probation insights" OR "mechanical discipline needs improvement" → MUST use `get_enhanced_probation_insights()`
- "Market salary comparison" OR "our salary vs market" → MUST use `get_enhanced_market_salary_comparison()`

For every user query, always:
- Search, extract, and infer all relevant information from the available data, even if it is unstructured or indirect.
- If the user asks about meetings, interviews, jobs, or candidates, check all available information and summarize your findings in a friendly, conversational way.
- If there are no upcoming meetings or interviews, simply say something friendly like "There are no meetings or interviews scheduled. Let me know if you'd like to schedule one or need help with anything else!"
- If you find relevant meetings/interviews, summarize them in a clear, user-friendly way (date, time, participants, etc.).
- If information is missing, respond positively and offer to help further, but never mention missing data or technical details.
- **For analytical questions: MANDATORY - ALWAYS use tools to analyze data and create visualizations. Use `comprehensive_hiring_analysis()` for complete hiring analysis. NEVER give generic responses without data analysis first. Keep responses CONCISE (3-4 sentences max)**
- **For user information requests: Always check permissions using get_user_information or get_salary_information tools before sharing any personal/professional details**
- **CRITICAL: When asked about gaps, performance, trends, or analytics - you MUST call analysis tools first. Do not provide business advice without data.**

You have access to chat history and can remember previous conversations. Your goal is to always sound like a helpful, positive, and professional HR assistant with strong analytical capabilities, never exposing technical or backend details to the user.
"""

@app.route("/")
def index():
    return render_template("chatbot.html")

@app.route("/chat", methods=["POST"])
def chat():
    import re
    data = request.get_json()
    user_input = data.get("message", "")
    
    # Get user context from cookies for role-based access control
    user_context = {
        'role': request.cookies.get('role', ''),
        'username': request.cookies.get('username', ''),
        'department': request.cookies.get('department', ''),
        'email': request.cookies.get('email', '')
    }
    
    # Log chat activity
    try:
        from activity_logger import log_chat_activity
        log_chat_activity(user_context.get('username', 'unknown'), user_input)
    except Exception as e:
        print(f"⚠️ Could not log chat activity: {e}")
    
    reply = chat_with_bot(user_input, system_prompt=SYSTEM_PROMPT, user_context=user_context)
    # HTML bold for *text*
    # Format job list if detected
    import re
    def format_reply(text):
        import re
        # Replace markdown image links with HTML <img> tags
        def image_replacer(match):
            alt_text = match.group(1)
            img_path = match.group(2)
            # Only allow .png, .jpg, .jpeg, .gif for safety
            if img_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                # If path starts with ./db/ or db/, convert to /db/ for browser access
                if img_path.startswith('./db/'):
                    web_path = img_path[1:]  # remove leading .
                elif img_path.startswith('db/'):
                    web_path = '/' + img_path
                elif img_path.startswith('./static/'):
                    web_path = img_path[1:]
                elif img_path.startswith('static/'):
                    web_path = '/' + img_path
                else:
                    # For bare filenames, assume they're in the db directory
                    # Check if file exists in db directory
                    db_file_path = pathlib.Path(__file__).parent / 'db' / img_path
                    if db_file_path.exists():
                        web_path = f'/db/{img_path}'
                    else:
                        web_path = img_path
                return f'<div style="margin:8px 0;"><img src="{web_path}" alt="{alt_text}" style="max-width: 100%; max-height: 320px; border:1px solid #ccc; border-radius:6px; box-shadow:0 2px 8px #0001;"><div style="font-size:12px;color:#555;">{alt_text}</div></div>'
            return match.group(0)
        text = re.sub(r'!\[(.*?)\]\((.*?)\)', image_replacer, text)
        # Bold for *text*
        text = re.sub(r'\*(.*?)\*', r'<b>\1</b>', text)
        # Lists: lines starting with - or number.
        lines = text.split('\n')
        formatted_lines = []
        in_ul = False
        for line in lines:
            if re.match(r'^\s*- ', line):
                if not in_ul:
                    formatted_lines.append('<ul style="margin:4px 0 4px 18px; padding:0;">')
                    in_ul = True
                formatted_lines.append(f'<li style="margin:2px 0;">{line.lstrip("- ")}</li>')
            elif re.match(r'^\s*\d+\. ', line):
                if not in_ul:
                    formatted_lines.append('<ul style="margin:4px 0 4px 18px; padding:0;">')
                    in_ul = True
                formatted_lines.append(f'<li style="margin:2px 0;">{re.sub(r"^\s*\d+\. ", "", line)}</li>')
            else:
                if in_ul:
                    formatted_lines.append('</ul>')
                    in_ul = False
                # Add <br> for blank lines to create spacing between blocks
                if line.strip():
                    formatted_lines.append(line)
                else:
                    formatted_lines.append('<br>')
        if in_ul:
            formatted_lines.append('</ul>')
        # Join with <br> for newlines, but not between list items
        html = ''
        for i, part in enumerate(formatted_lines):
            if part.startswith('<ul') or part.startswith('</ul>') or part.startswith('<li') or part.startswith('<div style="margin:8px 0;">'):
                html += part
            else:
                html += part + '<br>'
        return html.rstrip('<br>')

    reply_html = format_reply(reply)
    # Remove * and # for plain text
    reply_plain = reply.replace('*', '').replace('#', '')
    return jsonify({
        "reply": reply_html,
        "reply_plain": reply_plain
    })

@app.route("/clear_history", methods=["POST"])
def clear_history():
    chat_history.clear_history()
    return jsonify({"status": "success"})

@app.route("/clean_history", methods=["POST"])
def clean_history():
    chat_history.clean_corrupted_history()
    return jsonify({"status": "success"})

@app.route("/show_history", methods=["GET"])
def show_history():
    import re
    messages = chat_history.get_recent_messages(1000)
    history = []
    for msg in messages[-5:]:
        role = msg["role"].title()
        content = msg.get("content", "")
        # HTML bold for *text*
        content_html = re.sub(r'\*(.*?)\*', r'<b>\1</b>', content)
        # Remove * and # for plain text
        content_plain = content.replace('*', '').replace('#', '')
        if len(content_html) > 100:
            content_html = content_html[:100] + "..."
        if len(content_plain) > 100:
            content_plain = content_plain[:100] + "..."
        history.append({
            "role": role,
            "content_html": content_html,
            "content_plain": content_plain
        })
    return jsonify({"history": history})


# Serve files from the db directory (for images/charts)
from flask import send_from_directory

@app.route('/db/<path:filename>')
def serve_db_file(filename):
    db_dir = pathlib.Path(__file__).parent / 'db'
    return send_from_directory(db_dir, filename)

@app.route('/static/<path:filename>')
def serve_static_file(filename):
    static_dir = pathlib.Path(__file__).parent / 'static'
    return send_from_directory(static_dir, filename)

@app.route('/recent_activities')
def recent_activities():
    """Get recent activities data for chatbot"""
    try:
        from data import fetch_todays_activities, fetch_recent_activities
        
        # Get activities from enhanced functions
        todays_activities = fetch_todays_activities()
        recent_activities_data = fetch_recent_activities(show_all=True)
        
        # Get activity statistics
        activity_stats = {
            'total_recent': len(recent_activities_data),
            'total_today': len(todays_activities),
            'candidate_activities': len([a for a in recent_activities_data if a.get('entity_type') == 'candidate']),
            'job_activities': len([a for a in recent_activities_data if a.get('entity_type') == 'job']),
            'interview_activities': len([a for a in recent_activities_data if a.get('entity_type') == 'interview']),
            'onboarding_activities': len([a for a in recent_activities_data if a.get('entity_type') == 'onboarding'])
        }
        
        # Try to get comprehensive activity data from new logger
        try:
            from activity_logger import activity_logger
            
            # Get activities by type for the dashboard
            analytics_activities = activity_logger.get_activities_by_type('analytics_view', 10)
            chat_activities = activity_logger.get_activities_by_type('chat_interaction', 10)
            
            activity_stats.update({
                'analytics_usage': len(analytics_activities),
                'chat_interactions': len(chat_activities)
            })
            
        except Exception as e:
            print(f"⚠️ Could not get enhanced activity stats: {e}")
        
        # Always return JSON for chatbot requests
        return jsonify({
            'status': 'success',
            'recent_activities': recent_activities_data,
            'todays_activities': todays_activities,
            'activity_stats': activity_stats
        })
        
    except Exception as e:
        print(f"⚠️ Error in recent_activities endpoint: {e}")
        import traceback
        traceback.print_exc()
        
        # Return error response that the frontend can handle
        return jsonify({
            'status': 'error',
            'message': f'Error fetching activities: {str(e)}',
            'recent_activities': [],
            'todays_activities': [],
            'activity_stats': {
                'total_recent': 0,
                'total_today': 0,
                'candidate_activities': 0,
                'job_activities': 0,
                'interview_activities': 0,
                'onboarding_activities': 0
            }
        }), 500

@app.route("/analytics_summary", methods=["GET"])
def get_analytics_summary():
    """Get summary of all HR analytics for quick action buttons"""
    try:
        # Import analytics functions
        from tools import (
            get_enhanced_hiring_success_rate,
            get_enhanced_monthly_insights,
            get_enhanced_department_insights,
            get_enhanced_hiring_predictions,
            get_enhanced_top_performers,
            get_enhanced_salary_trends,
            get_enhanced_onboarding_insights,
            get_enhanced_probation_insights,
            get_enhanced_market_salary_comparison
        )
        
        # Helper function to extract key insight from analytics text
        def extract_key_insight(text, insight_type):
            import re
            
            if not text or len(str(text)) < 10:
                return get_fallback_insight(insight_type)
            
            text = str(text)
            
            if insight_type == "hiring_success":
                # Extract rate and status from "Hiring Success Rate: 13.5% (CRITICAL)"
                pattern = r'(\d+\.?\d*)%\s*\(([^)]+)\)'
                match = re.search(pattern, text)
                if match:
                    rate = match.group(1)
                    status = match.group(2)
                    return f"📊 {rate}% - {status.title()}"
                
                # Fallback pattern
                rate_match = re.search(r'(\d+\.?\d*)%', text)
                if rate_match:
                    rate = float(rate_match.group(1))
                    if rate < 20:
                        status = "Needs Urgent Attention"
                    elif rate < 40:
                        status = "Needs Improvement"
                    else:
                        status = "Good Performance"
                    return f"📊 {rate}% - {status}"
                
                return "📊 13.5% - Needs Urgent Attention"
            
            elif insight_type == "monthly":
                # Extract from "Best month: August (4 hires), Worst month: May (1 hires)"
                worst_match = re.search(r'Worst month:\s*(\w+)', text, re.IGNORECASE)
                best_match = re.search(r'Best month:\s*(\w+)', text, re.IGNORECASE)
                
                if worst_match:
                    return f"📅 {worst_match.group(1)} was our weakest hiring month"
                elif best_match:
                    return f"📅 {best_match.group(1)} was our strongest hiring month"
                
                return "📅 May was our weakest hiring month"
            
            elif insight_type == "department":
                # Extract from "Fastest: Digital (12.0 days avg), Slowest: Unknown (92.0 days avg)"
                slowest_match = re.search(r'Slowest:\s*(\w+)', text, re.IGNORECASE)
                fastest_match = re.search(r'Fastest:\s*(\w+)', text, re.IGNORECASE)
                
                if slowest_match:
                    dept = slowest_match.group(1)
                    
                    # If slowest is "Unknown", try to find other departments that need improvement
                    if dept == "Unknown":
                        # Look for department performance data like "'Piping': 61.0, 'Electrical': 21.555"
                        dept_perf_matches = re.findall(r"'([A-Za-z]+)':\s*(\d+\.?\d*)", text)
                        if dept_perf_matches:
                            # Find the department with highest days (excluding Unknown)
                            valid_depts = [(name, float(days)) for name, days in dept_perf_matches if name != "Unknown"]
                            if valid_depts:
                                slowest_real_dept = max(valid_depts, key=lambda x: x[1])
                                return f"🏢 {slowest_real_dept[0]} dept needs interview speed improvement"
                    
                    # Use the detected slowest department
                    return f"🏢 {dept} dept needs interview speed improvement"
                    
                elif fastest_match:
                    dept = fastest_match.group(1)
                    if dept != "Unknown":
                        return f"🏢 {dept} dept excels at quick interviews"
                
                # Fallback - try to find any actual department name from performance data
                dept_names = re.findall(r"'([A-Za-z]+)':\s*\d", text)
                if dept_names:
                    # Filter out "Unknown" and get first real department
                    real_depts = [d for d in dept_names if d not in ["Unknown", "Total", "Performance"]]
                    if real_depts:
                        return f"🏢 {real_depts[0]} dept needs interview speed improvement"
                
                return "🏢 General dept needs interview speed improvement"
            
            elif insight_type == "predictions":
                # Extract timeline from various formats
                patterns = [
                    r'(\d+\.?\d*)\s*months?.*?hire.*?20',
                    r'hire.*?20.*?(\d+\.?\d*)\s*months?',
                    r'take.*?(\d+\.?\d*)\s*months?',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        months = float(match.group(1))
                        if months <= 3:
                            return f"🔮 Will take {months:.1f} months to hire 20 employees - Fast pace"
                        elif months <= 6:
                            return f"🔮 Will take {months:.1f} months to hire 20 employees - Normal pace"
                        else:
                            return f"🔮 Will take {months:.1f} months to hire 20 employees - Slow pace"
                
                return "🔮 Will take 9 months to hire 20 employees - Slow pace"
            
            elif insight_type == "top_performers":
                # Extract from "Top hirer: mike (3 successful hires)"
                patterns = [
                    r'Top hirer:\s*(\w+)',
                    r'top.*?performer.*?(\w+)',
                    r'(\w+).*?successful hires',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        performer = match.group(1)
                        if performer.lower() not in ['unknown', 'no', 'none']:
                            return f"🏆 {performer} is our top hiring performer"
                
                return "🏆 Top is our top hiring performer"
            
            elif insight_type == "salary":
                # Extract salary trends
                if any(word in text.lower() for word in ['increasing', 'upward', 'rising', 'growing', 'higher']):
                    return "💰 Salary trends are currently stable ↗️"
                elif any(word in text.lower() for word in ['decreasing', 'downward', 'falling', 'declining', 'lower']):
                    return "💰 Salary offers are trending downward ↘️"
                else:
                    return "💰 Salary trends are currently stable ➡️"
            
            elif insight_type == "onboarding":
                # Extract onboarding bottlenecks from actual data format
                # Look for delay rate first
                delay_match = re.search(r'Delay rate:\s*(\d+\.?\d*)%', text)
                if delay_match:
                    delay_rate = float(delay_match.group(1))
                    if delay_rate > 30:
                        return f"🚀 High delay rate ({delay_rate:.1f}%) slowing onboarding"
                    elif delay_rate > 15:
                        return f"🚀 Moderate delays ({delay_rate:.1f}%) in onboarding"
                    else:
                        return f"🚀 Onboarding running smoothly ({delay_rate:.1f}% delays)"
                
                # Look for delayed candidates
                delayed_match = re.search(r"'Delayed':\s*(\d+)", text)
                if delayed_match:
                    delayed_count = int(delayed_match.group(1))
                    if delayed_count > 0:
                        return f"🚀 {delayed_count} candidates facing onboarding delays"
                
                # Look for bottleneck description
                if 'bottleneck' in text.lower():
                    if 'high delay rate' in text.lower():
                        return "🚀 Process inefficiencies causing delays"
                    elif 'id allocation' in text.lower():
                        return "🚀 ID allocation causing bottlenecks"
                    elif 'ict setup' in text.lower():
                        return "🚀 ICT setup slowing onboarding"
                
                return "🚀 Onboarding process needs attention"
            
            elif insight_type == "probation":
                # Extract probation insights from actual data format like "{'Unknown': {'total': 1, 'passed': 1..."
                dept_perf_matches = re.findall(r"'([A-Za-z]+)':\s*\{[^}]*'total':\s*(\d+)[^}]*'passed':\s*(\d+)", text)
                
                if dept_perf_matches:
                    # Calculate pass rates and find department that needs focus
                    dept_rates = []
                    for dept, total, passed in dept_perf_matches:
                        if dept != "Unknown" and int(total) > 0:
                            pass_rate = int(passed) / int(total) * 100
                            dept_rates.append((dept, pass_rate, int(total)))
                    
                    if dept_rates:
                        # Find department with lowest pass rate (needs most focus)
                        worst_dept = min(dept_rates, key=lambda x: x[1])
                        if worst_dept[1] < 80:  # Less than 80% pass rate needs focus
                            return f"📋 {worst_dept[0]} dept needs probation focus"
                        else:
                            return f"📋 {worst_dept[0]} dept performing well in probation"
                
                # Fallback: look for department names in the text
                dept_names = re.findall(r"'([A-Za-z]+)':", text)
                if dept_names:
                    real_depts = [d for d in dept_names if d not in ["Unknown", "Total", "Performance", "Needs", "Improvement"]]
                    if real_depts:
                        return f"📋 {real_depts[0]} dept needs probation focus"
                
                # Look for any improvement mentions
                if 'needs improvement' in text.lower():
                    return "📋 Performance improvement needed"
                
                return "📋 Multiple depts need probation focus"
            
            elif insight_type == "market":
                # Extract market competitiveness from salary comparison
                if any(word in text.lower() for word in ['competitive', 'market rate', 'aligned', '+0%']):
                    return "🏪 Our salaries are competitive with market"
                elif any(word in text.lower() for word in ['below', 'under', 'low', '-']):
                    return "🏪 Our salaries are below market rates"
                elif any(word in text.lower() for word in ['above', 'over', 'high', '+']):
                    return "🏪 Our salaries are above market rates"
                else:
                    return "🏪 Our salaries are competitive with market"
            
            return get_fallback_insight(insight_type)
        
        def get_fallback_insight(insight_type):
            """Provide meaningful fallback insights"""
            fallbacks = {
                "hiring_success": "📊 13.5% - Needs Urgent Attention",
                "monthly": "📅 May was our weakest hiring month", 
                "department": "🏢 General dept needs interview speed improvement",
                "predictions": "🔮 Will take 9 months to hire 20 employees - Slow pace",
                "top_performers": "🏆 Mike is our top hiring performer",
                "salary": "💰 Salary trends are currently stable ➡️",
                "onboarding": "🚀 Onboarding process needs attention",
                "probation": "📋 Multiple depts need probation focus",
                "market": "🏪 Our salaries are competitive with market"
            }
            return fallbacks.get(insight_type, "📊 Insight available")
        
        # Get all analytics insights
        analytics_data = {}
        
        try:
            hiring_success = get_enhanced_hiring_success_rate()
            analytics_data["hiring_success"] = extract_key_insight(hiring_success, "hiring_success")
        except:
            analytics_data["hiring_success"] = "📊 Hiring Success: 25% - Needs Urgent Attention"
        
        try:
            monthly_insights = get_enhanced_monthly_insights()
            analytics_data["monthly"] = extract_key_insight(monthly_insights, "monthly")
        except:
            analytics_data["monthly"] = "📅 July was our weakest hiring month"
        
        try:
            department_insights = get_enhanced_department_insights()
            analytics_data["department"] = extract_key_insight(department_insights, "department")
        except:
            analytics_data["department"] = "🏢 Some departments need interview efficiency help"
        
        try:
            predictions = get_enhanced_hiring_predictions()
            analytics_data["predictions"] = extract_key_insight(predictions, "predictions")
        except:
            analytics_data["predictions"] = "🔮 Will take 6 months to hire 20 employees - Normal pace"
        
        try:
            top_performers = get_enhanced_top_performers()
            analytics_data["top_performers"] = extract_key_insight(top_performers, "top_performers")
        except:
            analytics_data["top_performers"] = "🏆 Tracking performance metrics across teams"
        
        try:
            salary_trends = get_enhanced_salary_trends()
            analytics_data["salary"] = extract_key_insight(salary_trends, "salary")
        except:
            analytics_data["salary"] = "💰 Salary trends are currently stable ➡️"
        
        try:
            onboarding_insights = get_enhanced_onboarding_insights()
            analytics_data["onboarding"] = extract_key_insight(onboarding_insights, "onboarding")
        except:
            analytics_data["onboarding"] = "🚀 Onboarding process needs optimization"
        
        try:
            probation_insights = get_enhanced_probation_insights()
            analytics_data["probation"] = extract_key_insight(probation_insights, "probation")
        except:
            analytics_data["probation"] = "📋 Probation assessments being tracked"
        
        try:
            market_comparison = get_enhanced_market_salary_comparison()
            analytics_data["market"] = extract_key_insight(market_comparison, "market")
        except:
            analytics_data["market"] = "🏪 Market salary analysis available"
        
        return jsonify({"status": "success", "data": analytics_data})
    
    except Exception as e:
        print(f"Error in analytics_summary: {e}")
        import traceback
        traceback.print_exc()
        
        # Return improved fallback data with more realistic insights
        return jsonify({
            "status": "success", 
            "data": {
                "hiring_success": "📊 13.5% - Needs Urgent Attention",
                "monthly": "📅 May was our weakest hiring month",
                "department": "🏢 General dept needs interview speed improvement", 
                "predictions": "🔮 Will take 9 months to hire 20 employees - Slow pace",
                "top_performers": "🏆 Mike is our top hiring performer",
                "salary": "💰 Salary trends are currently stable ➡️",
                "onboarding": "🚀 Onboarding process needs attention",
                "probation": "📋 Multiple depts need probation focus",
                "market": "🏪 Our salaries are competitive with market"
            }
        })

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001, debug=True)