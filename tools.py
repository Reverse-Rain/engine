# -----------------------------------------------------------------------------------------------------------------
# CLEAN TOOLS.PY - REAL DATA ANALYTICS ONLY
# -----------------------------------------------------------------------------------------------------------------
from typing import Dict, List, Any
import os
import json
import numpy as np
# Configure matplotlib to use non-interactive backend for web servers
import matplotlib
matplotlib.use('Agg')  # Use Anti-Grain Geometry backend (non-interactive)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# Import salary research module for market analysis
try:
    from salary_research import salary_researcher
except ImportError:
    salary_researcher = None

def load_json_data(filename):
    """Load JSON data from the db folder"""
    db_folder = os.path.join(os.path.dirname(__file__), 'db')
    file_path = os.path.join(db_folder, filename)
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

# ========== REAL DATA ANALYTICS FUNCTIONS ==========

def get_onboarding_insights() -> str:
    """Analyzes onboarding process based on real candidate data"""
    try:
        candidates = load_json_data("candidates.json")
        
        hired_candidates = [c for c in candidates if c.get('status') == 'Hired']
        
        if not hired_candidates:
            return "🚀 **Onboarding Insights**: No hired candidates found for analysis"
        
        # Analyze real onboarding data from candidate records
        onboarding_analysis = {
            'total_hired': len(hired_candidates),
            'pending_onboarding': 0,
            'completed_onboarding': 0,
            'avg_hiring_to_start_days': 0,
            'departments': {}
        }
        
        total_days = 0
        valid_date_count = 0
        
        for candidate in hired_candidates:
            # Analyze department distribution
            dept = candidate.get('department', 'Unknown')
            if dept not in onboarding_analysis['departments']:
                onboarding_analysis['departments'][dept] = 0
            onboarding_analysis['departments'][dept] += 1
            
            # Calculate time from hiring to start (if available)
            hired_date = candidate.get('hired_date')
            start_date = candidate.get('start_date')
            
            if hired_date and start_date:
                try:
                    hired_dt = datetime.strptime(hired_date, '%Y-%m-%d')
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    days_diff = (start_dt - hired_dt).days
                    total_days += days_diff
                    valid_date_count += 1
                except:
                    pass
            
            # Check onboarding status
            onboarding_status = candidate.get('onboarding_status', 'pending')
            if onboarding_status == 'completed':
                onboarding_analysis['completed_onboarding'] += 1
            else:
                onboarding_analysis['pending_onboarding'] += 1
        
        if valid_date_count > 0:
            onboarding_analysis['avg_hiring_to_start_days'] = total_days / valid_date_count
        
        # Generate insights based on real data
        completion_rate = (onboarding_analysis['completed_onboarding'] / onboarding_analysis['total_hired']) * 100
        
        # Recommendations based on actual data
        recommendations = []
        if completion_rate < 80:
            recommendations.append("Improve onboarding completion tracking")
        if onboarding_analysis['avg_hiring_to_start_days'] > 14:
            recommendations.append("Reduce time between hiring and start date")
        if onboarding_analysis['pending_onboarding'] > 3:
            recommendations.append("Focus on completing pending onboardings")
        
        dept_breakdown = "\n".join([f"• {dept}: {count} hires" for dept, count in onboarding_analysis['departments'].items()])
        
        return f"""🚀 **Onboarding Insights** (Real Data Analysis)

**Current Status**:
• Total Hired: {onboarding_analysis['total_hired']} candidates
• Completed Onboarding: {onboarding_analysis['completed_onboarding']} ({completion_rate:.1f}%)
• Pending Onboarding: {onboarding_analysis['pending_onboarding']}

**Time Analysis**:
• Average Hiring to Start: {onboarding_analysis['avg_hiring_to_start_days']:.1f} days

**Department Distribution**:
{dept_breakdown}

**Recommendations**:
{chr(10).join([f"• {rec}" for rec in recommendations]) if recommendations else "• Current onboarding process is performing well"}

**Action Items**:
• Track onboarding completion status for all hires
• Set up start date coordination process
• Monitor department-specific onboarding needs
"""
    except Exception as e:
        return f"⚠️ Error analyzing onboarding: {e}"

def get_probation_insights() -> str:
    """Analyzes probation assessment performance based on real data"""
    try:
        candidates = load_json_data("candidates.json")
        
        hired_candidates = [c for c in candidates if c.get('status') == 'Hired']
        
        if not hired_candidates:
            return "🎓 **Probation Assessment Insights**: No hired candidates found for analysis"
        
        # Analyze real probation data
        probation_analysis = {
            'total_on_probation': 0,
            'passed_probation': 0,
            'failed_probation': 0,
            'pending_assessment': 0,
            'departments': {}
        }
        
        for candidate in hired_candidates:
            dept = candidate.get('department', 'Unknown')
            if dept not in probation_analysis['departments']:
                probation_analysis['departments'][dept] = {
                    'total': 0, 'passed': 0, 'failed': 0, 'pending': 0
                }
            
            probation_status = candidate.get('probation_status', 'pending')
            probation_analysis['departments'][dept]['total'] += 1
            
            if probation_status == 'passed':
                probation_analysis['passed_probation'] += 1
                probation_analysis['departments'][dept]['passed'] += 1
            elif probation_status == 'failed':
                probation_analysis['failed_probation'] += 1
                probation_analysis['departments'][dept]['failed'] += 1
            else:
                probation_analysis['pending_assessment'] += 1
                probation_analysis['departments'][dept]['pending'] += 1
            
            probation_analysis['total_on_probation'] += 1
        
        # Calculate pass rates by department
        dept_stats = []
        for dept, data in probation_analysis['departments'].items():
            if data['total'] > 0:
                pass_rate = (data['passed'] / data['total']) * 100
                dept_stats.append({
                    'department': dept,
                    'pass_rate': pass_rate,
                    'total': data['total'],
                    'passed': data['passed'],
                    'failed': data['failed'],
                    'pending': data['pending']
                })
        
        dept_stats.sort(key=lambda x: x['pass_rate'], reverse=True)
        
        overall_pass_rate = (probation_analysis['passed_probation'] / probation_analysis['total_on_probation'] * 100) if probation_analysis['total_on_probation'] > 0 else 0
        
        # Generate department breakdown
        dept_breakdown = "\n".join([
            f"• {stat['department']}: {stat['pass_rate']:.1f}% pass rate ({stat['passed']}/{stat['total']})"
            for stat in dept_stats
        ])
        
        # Recommendations
        recommendations = []
        if overall_pass_rate < 80:
            recommendations.append("Overall probation pass rate needs improvement")
        if probation_analysis['pending_assessment'] > 5:
            recommendations.append("Address pending probation assessments promptly")
        
        # Find departments needing attention
        underperforming_depts = [stat for stat in dept_stats if stat['pass_rate'] < 75]
        if underperforming_depts:
            recommendations.append(f"Focus on improving {', '.join([d['department'] for d in underperforming_depts])}")
        
        return f"""🎓 **Probation Assessment Insights** (Real Data Analysis)

**Overall Performance**:
• Total on Probation: {probation_analysis['total_on_probation']} candidates
• Passed: {probation_analysis['passed_probation']} ({overall_pass_rate:.1f}%)
• Failed: {probation_analysis['failed_probation']}
• Pending Assessment: {probation_analysis['pending_assessment']}

**Department Performance**:
{dept_breakdown}

**Recommendations**:
{chr(10).join([f"• {rec}" for rec in recommendations]) if recommendations else "• Probation process is performing well across departments"}

**Action Items**:
• Complete pending probation assessments
• Provide additional support to underperforming departments
• Track probation success factors
"""
    except Exception as e:
        return f"⚠️ Error analyzing probation data: {e}"

def get_salary_trend_insights() -> str:
    """Analyzes salary trends using real data with market comparison"""
    try:
        candidates = load_json_data("candidates.json")
        
        # Extract salary data with dates
        salary_data = []
        for candidate in candidates:
            if candidate.get('offered_salary') and candidate.get('hired_date'):
                try:
                    salary = float(candidate['offered_salary'])
                    date = datetime.strptime(candidate['hired_date'], '%Y-%m-%d')
                    position = candidate.get('position', 'Unknown')
                    salary_data.append({
                        'salary': salary, 
                        'date': date, 
                        'position': position
                    })
                except:
                    continue
        
        if len(salary_data) < 2:
            return "💰 **Salary Trend Analysis**: No salary data available in candidate records. This is normal as salary information is often stored separately for privacy."
        
        # Sort by date
        salary_data.sort(key=lambda x: x['date'])
        
        # Calculate trend
        if len(salary_data) >= 6:
            recent_avg = sum([s['salary'] for s in salary_data[-6:]]) / 6  # Last 6 hires
            older_avg = sum([s['salary'] for s in salary_data[:-6]]) / (len(salary_data) - 6)   # Previous hires
        else:
            # If less than 6 data points, split in half
            mid_point = len(salary_data) // 2
            recent_avg = sum([s['salary'] for s in salary_data[mid_point:]]) / (len(salary_data) - mid_point)
            older_avg = sum([s['salary'] for s in salary_data[:mid_point]]) / mid_point if mid_point > 0 else 0
        
        trend_pct = ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0
        trend_direction = "📈 INCREASING" if trend_pct > 0 else "📉 DECREASING"
        
        # Analyze by position
        position_trends = {}
        for position in set([s['position'] for s in salary_data]):
            pos_data = [s for s in salary_data if s['position'] == position]
            if len(pos_data) >= 2:
                pos_avg = sum([s['salary'] for s in pos_data]) / len(pos_data)
                position_trends[position] = pos_avg
        
        position_breakdown = "\n".join([f"• {pos}: ${avg:,.0f} average" for pos, avg in position_trends.items()])
        
        return f"""💰 **Salary Trend Analysis** (Real Data Analysis)

**Overall Trend**: {trend_direction} by {abs(trend_pct):.1f}%
**Current Average**: ${recent_avg:,.0f}
**Previous Average**: ${older_avg:,.0f}
**Data Points**: {len(salary_data)} hired candidates

**Position Breakdown**:
{position_breakdown}

**Insights**:
• Salary progression {'aligns with growth strategy' if trend_pct > 0 else 'may need review'}
• {'Competitive increases' if trend_pct > 5 else 'Modest adjustments' if trend_pct > 0 else 'Declining trend requires attention'}
• Analysis based on real hiring data

**Recommendations**:
• {'Continue current strategy' if trend_pct > 0 else 'Review compensation packages'}
• Regular market benchmarking
• Document salary decision factors

*Analysis based on {len(salary_data)} real salary data points*
"""
    except Exception as e:
        return f"⚠️ Error analyzing salary trends: {e}"

def get_market_salary_comparison() -> str:
    """Compares company salary offerings with market rates using internet research"""
    try:
        candidates = load_json_data("candidates.json")
        
        # Extract real salary data from hired candidates
        salary_by_position = {}
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired':
                position = candidate.get('position', 'Unknown')
                offered_salary = candidate.get('offered_salary')
                
                if offered_salary:
                    try:
                        salary_amount = float(offered_salary)
                        if position not in salary_by_position:
                            salary_by_position[position] = []
                        salary_by_position[position].append(salary_amount)
                    except (ValueError, TypeError):
                        continue
        
        if not salary_by_position:
            return """💰 **Market Salary Comparison**: No salary data available for hired candidates

**Note**: This is common as salary information is often:
• Stored in separate HR systems for privacy
• Managed by payroll departments
• Kept confidential in candidate records

**To Enable Market Comparison**:
• Add 'offered_salary' field to candidate records
• Use the salary research module for market data
• Implement salary benchmarking process

**Current Status**: Ready for analysis once salary data is available"""
        
        # Analyze each position with market research
        comparison_results = []
        
        for position, salaries in salary_by_position.items():
            if len(salaries) >= 1:  # At least one salary data point
                internal_avg = sum(salaries) / len(salaries)
                internal_min = min(salaries)
                internal_max = max(salaries)
                
                # Research market salary for this position if available
                market_avg = 0
                competitiveness = 0
                status = "🔍 Research Unavailable"
                
                if salary_researcher:
                    try:
                        market_research = salary_researcher.research_market_salary(position)
                        
                        if market_research['status'] == 'success':
                            market_data = market_research['salary_data']
                            market_avg = market_data['average_salary']
                            
                            # Calculate competitiveness
                            competitiveness = (internal_avg / market_avg) * 100 if market_avg > 0 else 0
                            
                            if competitiveness >= 110:
                                status = "💚 Above Market"
                            elif competitiveness >= 90:
                                status = "💛 Market Competitive"
                            else:
                                status = "🔴 Below Market"
                    except:
                        pass
                
                comparison_results.append({
                    'position': position,
                    'internal_avg': internal_avg,
                    'market_avg': market_avg,
                    'competitiveness': competitiveness,
                    'status': status,
                    'count': len(salaries)
                })
        
        if not comparison_results:
            return "💰 **Market Salary Comparison**: Unable to analyze salary data"
        
        # Generate comparison report
        position_breakdown = "\n".join([
            f"• {result['position']}: ${result['internal_avg']:,.0f} internal vs ${result['market_avg']:,.0f} market ({result['competitiveness']:.1f}%) {result['status']}"
            if result['market_avg'] > 0 else f"• {result['position']}: ${result['internal_avg']:,.0f} internal {result['status']}"
            for result in comparison_results
        ])
        
        # Overall recommendations
        below_market = [r for r in comparison_results if r['competitiveness'] > 0 and r['competitiveness'] < 90]
        above_market = [r for r in comparison_results if r['competitiveness'] >= 110]
        
        recommendations = []
        if below_market:
            recommendations.append(f"Consider salary adjustments for: {', '.join([r['position'] for r in below_market])}")
        if above_market:
            recommendations.append(f"Excellent competitive positioning for: {', '.join([r['position'] for r in above_market])}")
        if not below_market and not above_market:
            recommendations.append("Most positions are competitively positioned")
        
        avg_competitiveness = sum([r['competitiveness'] for r in comparison_results if r['competitiveness'] > 0])
        avg_count = len([r for r in comparison_results if r['competitiveness'] > 0])
        avg_competitiveness = avg_competitiveness / avg_count if avg_count > 0 else 0
        
        return f"""💰 **Market Salary Comparison** (Real Data + Internet Research)

**Overall Competitiveness**: {avg_competitiveness:.1f}% of market rate

**Position Analysis**:
{position_breakdown}

**Market Intelligence**:
• Research conducted using current market data
• Salaries compared against industry standards
• Analysis based on real internal hiring data

**Recommendations**:
{chr(10).join([f"• {rec}" for rec in recommendations])}

**Action Items**:
• Review positions needing adjustment
• Monitor market trends quarterly
• Consider performance-based increases
• Benchmark against direct competitors

*Data sources: Market research + {sum([r['count'] for r in comparison_results])} internal salary data points*
"""
    except Exception as e:
        return f"⚠️ Error analyzing market salary comparison: {e}"

def get_hiring_success_rate_insight() -> str:
    """Analyzes hiring success rate using real candidate data"""
    try:
        candidates = load_json_data("candidates.json")
        
        if not candidates:
            return "📊 **Hiring Success Rate**: No candidate data available for analysis"
        
        total_candidates = len(candidates)
        hired_count = len([c for c in candidates if c.get('status') == 'Hired'])
        success_rate = (hired_count / total_candidates * 100) if total_candidates > 0 else 0
        
        # Monthly trend analysis
        monthly_data = {}
        for candidate in candidates:
            applied_date = candidate.get('applied_date')
            if applied_date:
                try:
                    month_key = datetime.strptime(applied_date, '%Y-%m-%d').strftime('%Y-%m')
                    if month_key not in monthly_data:
                        monthly_data[month_key] = {'total': 0, 'hired': 0}
                    monthly_data[month_key]['total'] += 1
                    if candidate.get('status') == 'Hired':
                        monthly_data[month_key]['hired'] += 1
                except:
                    continue
        
        # Analysis
        if success_rate >= 75:
            assessment = "EXCELLENT"
            reason = "success rate is above industry benchmark"
        elif success_rate >= 50:
            assessment = "GOOD" 
            reason = "success rate meets expectations"
        elif success_rate >= 25:
            assessment = "NEEDS IMPROVEMENT"
            reason = "success rate is below optimal levels"
        else:
            assessment = "CRITICAL"
            reason = "success rate requires immediate attention"
        
        # Monthly breakdown
        monthly_breakdown = ""
        if monthly_data:
            monthly_breakdown = "\n**Monthly Breakdown**:\n"
            for month, data in sorted(monthly_data.items()):
                rate = (data['hired'] / data['total'] * 100) if data['total'] > 0 else 0
                monthly_breakdown += f"• {month}: {data['hired']}/{data['total']} hired ({rate:.1f}%)\n"
            
        return f"""📊 **Hiring Success Rate Analysis** (Real Data)

**Current Rate**: {success_rate:.1f}% ({hired_count}/{total_candidates} candidates)
**Assessment**: {assessment} - {reason}

**Key Insights**:
• Total applications processed: {total_candidates}
• Successful hires: {hired_count}
• Conversion efficiency: {success_rate:.1f}%
{monthly_breakdown}
**Recommendations**:
• {'Maintain current strategies' if success_rate > 50 else 'Review screening and interview processes'}
• Implement data-driven candidate evaluation
• Track conversion rates by source and department

*Analysis based on {total_candidates} real candidate records*
"""
        
    except Exception as e:
        return f"⚠️ Error analyzing hiring success rate: {e}"

def get_monthly_hiring_insights() -> str:
    """Analyzes monthly hiring patterns using real data"""
    try:
        candidates = load_json_data("candidates.json")
        
        monthly_stats = {}
        for candidate in candidates:
            applied_date = candidate.get('applied_date')
            if applied_date:
                try:
                    month_key = datetime.strptime(applied_date, '%Y-%m-%d').strftime('%Y-%m')
                    month_name = datetime.strptime(month_key, '%Y-%m').strftime('%B %Y')
                    
                    if month_name not in monthly_stats:
                        monthly_stats[month_name] = {'applications': 0, 'hired': 0, 'interviews': 0}
                    
                    monthly_stats[month_name]['applications'] += 1
                    if candidate.get('status') == 'Hired':
                        monthly_stats[month_name]['hired'] += 1
                    if candidate.get('status') in ['Interviewed', 'Hired']:
                        monthly_stats[month_name]['interviews'] += 1
                except:
                    continue
        
        if not monthly_stats:
            return "📅 **Monthly Hiring Insights**: No application data available for analysis"
        
        # Find best and worst months
        success_rates = {month: (stats['hired'] / stats['applications'] * 100) if stats['applications'] > 0 else 0 
                        for month, stats in monthly_stats.items()}
        
        best_month = max(success_rates.keys(), key=lambda x: success_rates[x])
        worst_month = min(success_rates.keys(), key=lambda x: success_rates[x])
        
        monthly_breakdown = "\n".join([
            f"• {month}: {stats['hired']}/{stats['applications']} hired ({success_rates[month]:.1f}%)"
            for month, stats in sorted(monthly_stats.items())
        ])
        
        return f"""📅 **Monthly Hiring Insights** (Real Data Analysis)

**Best Month**: {best_month} ({success_rates[best_month]:.1f}% success rate)
**Worst Month**: {worst_month} ({success_rates[worst_month]:.1f}% success rate)

**Monthly Performance**:
{monthly_breakdown}

**Key Insights**:
• Total months analyzed: {len(monthly_stats)}
• Average monthly applications: {sum(s['applications'] for s in monthly_stats.values()) / len(monthly_stats):.1f}
• Overall success rate: {sum(s['hired'] for s in monthly_stats.values()) / sum(s['applications'] for s in monthly_stats.values()) * 100:.1f}%

**Recommendations**:
• Plan recruitment campaigns during high-performance months
• Investigate factors contributing to low-performance periods
• Maintain consistent hiring processes year-round

*Analysis based on {sum(s['applications'] for s in monthly_stats.values())} real applications*
"""
        
    except Exception as e:
        return f"⚠️ Error analyzing monthly insights: {e}"

def get_department_interview_insights() -> str:
    """Analyzes department interview efficiency using real data"""
    try:
        candidates = load_json_data("candidates.json")
        
        dept_stats = {}
        
        for candidate in candidates:
            dept = candidate.get('department', 'Unknown')
            status = candidate.get('status', '')
            
            if dept not in dept_stats:
                dept_stats[dept] = {'total': 0, 'interviewed': 0, 'hired': 0}
            
            dept_stats[dept]['total'] += 1
            
            if status in ['Interviewed', 'Hired']:
                dept_stats[dept]['interviewed'] += 1
            
            if status == 'Hired':
                dept_stats[dept]['hired'] += 1
        
        if not dept_stats:
            return "🏢 **Department Interview Efficiency**: No department data available"
        
        # Calculate efficiency metrics
        for dept, data in dept_stats.items():
            data['interview_rate'] = (data['interviewed'] / data['total'] * 100) if data['total'] > 0 else 0
            data['hire_rate'] = (data['hired'] / data['interviewed'] * 100) if data['interviewed'] > 0 else 0
        
        # Find most and least efficient departments
        fastest_dept = max(dept_stats.keys(), key=lambda x: dept_stats[x]['hire_rate'])
        slowest_dept = min(dept_stats.keys(), key=lambda x: dept_stats[x]['hire_rate'])
        
        dept_breakdown = "\n".join([
            f"• {dept}: {data['hire_rate']:.1f}% hire rate, {data['interviewed']}/{data['total']} interviewed"
            for dept, data in dept_stats.items()
        ])
        
        return f"""🏢 **Department Interview Efficiency Analysis** (Real Data)

**Most Efficient**: {fastest_dept} ({dept_stats[fastest_dept]['hire_rate']:.1f}% hire rate)
**Least Efficient**: {slowest_dept} ({dept_stats[slowest_dept]['hire_rate']:.1f}% hire rate)

**Department Performance**:
{dept_breakdown}

**Insights**:
• Based on {sum([data['total'] for data in dept_stats.values()])} real candidates
• {sum([data['hired'] for data in dept_stats.values()])} successful hires across departments
• Interview efficiency varies by department requirements

**Recommendations**:
• Share best practices from high-performing departments
• Provide interview training for lower-performing departments
• Standardize interview processes while respecting department needs

*Analysis based on real candidate and department data*
"""
        
    except Exception as e:
        return f"⚠️ Error analyzing department efficiency: {e}"

def get_top_performers_insights() -> str:
    """Identifies top performers using real data"""
    try:
        candidates = load_json_data("candidates.json")
        
        # Analyze interviewers/recruiters performance
        interviewer_stats = {}
        position_stats = {}
        
        for candidate in candidates:
            # Track interviewer performance
            interviewer = candidate.get('interviewed_by') or candidate.get('recruiter') or 'Unknown'
            if interviewer not in interviewer_stats:
                interviewer_stats[interviewer] = {'interviewed': 0, 'hired': 0}
            
            if candidate.get('status') in ['Interviewed', 'Hired']:
                interviewer_stats[interviewer]['interviewed'] += 1
            
            if candidate.get('status') == 'Hired':
                interviewer_stats[interviewer]['hired'] += 1
                
                # Track successful positions
                position = candidate.get('position', 'Unknown')
                if position not in position_stats:
                    position_stats[position] = 0
                position_stats[position] += 1
        
        # Calculate success rates
        for interviewer, stats in interviewer_stats.items():
            if stats['interviewed'] > 0:
                stats['success_rate'] = (stats['hired'] / stats['interviewed']) * 100
            else:
                stats['success_rate'] = 0
        
        # Find top performers
        top_interviewers = sorted(interviewer_stats.items(), 
                                key=lambda x: (x[1]['success_rate'], x[1]['hired']), 
                                reverse=True)[:5]
        
        top_positions = sorted(position_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        
        interviewer_breakdown = "\n".join([
            f"• {interviewer}: {stats['success_rate']:.1f}% success rate ({stats['hired']}/{stats['interviewed']})"
            for interviewer, stats in top_interviewers if stats['interviewed'] > 0
        ])
        
        position_breakdown = "\n".join([
            f"• {position}: {count} successful hires"
            for position, count in top_positions
        ])
        
        return f"""🏆 **Top Performers Analysis** (Real Data)

**Top Performing Interviewers**:
{interviewer_breakdown}

**Most Successful Positions**:
{position_breakdown}

**Key Insights**:
• Based on real interview and hiring data
• Success rates calculated from actual outcomes
• Performance varies by interviewer experience and role complexity

**Recommendations**:
• Share best practices from top performers
• Provide mentoring for developing interviewers
• Document successful interview techniques
• Create performance feedback loops

*Analysis based on real interviewer and hiring performance data*
"""
        
    except Exception as e:
        return f"⚠️ Error analyzing top performers: {e}"

# ========== CHART CREATION FUNCTIONS ==========

def create_line_chart(data: dict, filename: str, title: str, xlabel: str, ylabel: str) -> str:
    """Creates a line chart and saves it to the db folder"""
    try:
        plt.figure(figsize=(10, 6))
        
        dates = list(data.keys())
        values = list(data.values())
        
        plt.plot(dates, values, marker='o', linewidth=2, markersize=6)
        plt.title(title, fontsize=14, fontweight='bold')
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.grid(True, alpha=0.3)
        
        filepath = os.path.join("./db", filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        return f"Chart saved: {filename}"
        
    except Exception as e:
        return f"Error creating chart: {e}"

def create_pie_chart(data: Any) -> str:
    """Creates a pie chart based on the provided data"""
    try:
        plt.figure(figsize=(8, 8))
        
        if isinstance(data, dict):
            labels = list(data.keys())
            values = list(data.values())
        elif isinstance(data, list) and all(isinstance(item, dict) for item in data):
            labels = [item.get('category', f'Item {i}') for i, item in enumerate(data)]
            values = [item.get('value', 0) for item in data]
        else:
            return "⚠️ Invalid data format for pie chart"
        
        plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
        plt.title('Distribution Analysis', fontsize=14, fontweight='bold')
        
        filepath = os.path.join("./db", "pie_chart.png")
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        return f"📊 Pie chart created: ![Pie Chart](./db/pie_chart.png)"
        
    except Exception as e:
        return f"⚠️ Error creating pie chart: {e}"

# ========== UTILITY FUNCTIONS ==========

def greet(name: str) -> str:
    """Greets a user by name."""
    return f"Hello, {name}! Welcome to AION HR Analytics System."

def get_time(city: str = "UTC") -> str:
    """Returns current time."""
    try:
        return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    except Exception:
        return "Unable to get current time"

# ========== ENHANCED ANALYTICS FUNCTIONS ==========

def get_enhanced_hiring_success_rate() -> str:
    """Get comprehensive hiring success rate analysis with detailed breakdown"""
    try:
        candidates = load_json_data("candidates.json")
        
        # Status breakdown
        status_counts = {}
        total_candidates = len(candidates)
        hired_count = 0
        
        for candidate in candidates:
            status = candidate.get('status', 'Unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == 'Hired':
                hired_count += 1
        
        # Calculate success rate
        success_rate = (hired_count / total_candidates * 100) if total_candidates > 0 else 0
        
        # Determine performance status
        if success_rate < 15:
            performance = "CRITICAL"
        elif success_rate < 25:
            performance = "NEEDS IMPROVEMENT"
        elif success_rate < 40:
            performance = "GOOD"
        else:
            performance = "EXCELLENT"
        
        return f"Hiring Success Rate: {success_rate:.1f}% ({performance}) - {hired_count} hired out of {total_candidates} total candidates. Breakdown: {', '.join([f'{k}: {v}' for k, v in status_counts.items()])}"
    
    except Exception as e:
        return f"Error calculating hiring success rate: {str(e)}"

def get_enhanced_monthly_insights() -> str:
    """Get detailed monthly hiring trends and patterns"""
    from collections import defaultdict
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Monthly hiring breakdown
        monthly_hired = defaultdict(int)
        monthly_applied = defaultdict(int)
        
        for candidate in candidates:
            # Applied date analysis
            if candidate.get('applied_date'):
                try:
                    applied_month = datetime.strptime(candidate['applied_date'], '%Y-%m-%d').strftime('%B')
                    monthly_applied[applied_month] += 1
                except:
                    pass
            
            # Hired date analysis
            if candidate.get('status') == 'Hired' and candidate.get('hired_date'):
                try:
                    hired_month = datetime.strptime(candidate['hired_date'], '%Y-%m-%d').strftime('%B')
                    monthly_hired[hired_month] += 1
                except:
                    pass
        
        # Find best and worst months
        best_month = max(monthly_hired.items(), key=lambda x: x[1]) if monthly_hired else ("None", 0)
        worst_month = min(monthly_hired.items(), key=lambda x: x[1]) if monthly_hired else ("None", 0)
        
        insights = f"Monthly Hiring Insights: Best month: {best_month[0]} ({best_month[1]} hires), Worst month: {worst_month[0]} ({worst_month[1]} hires). "
        insights += f"Applications per month: {dict(monthly_applied)}"
        
        return insights
    
    except Exception as e:
        return f"Error analyzing monthly insights: {str(e)}"

def get_enhanced_department_insights() -> str:
    """Get department-specific interview efficiency and performance metrics"""
    from collections import defaultdict
    
    try:
        candidates = load_json_data("candidates.json")
        jobs = load_json_data("jobs.json")
        
        # Create job lookup
        job_lookup = {job['job_id']: job for job in jobs}
        
        # Department performance tracking
        dept_metrics = defaultdict(lambda: {'total': 0, 'hired': 0, 'avg_time': 0, 'times': []})
        
        for candidate in candidates:
            job_id = candidate.get('job_id', '1')
            job = job_lookup.get(job_id, {})
            department = job.get('department', 'Unknown')
            
            dept_metrics[department]['total'] += 1
            
            if candidate.get('status') == 'Hired':
                dept_metrics[department]['hired'] += 1
                
                # Calculate time to hire
                if candidate.get('applied_date') and candidate.get('hired_date'):
                    try:
                        applied = datetime.strptime(candidate['applied_date'], '%Y-%m-%d')
                        hired = datetime.strptime(candidate['hired_date'], '%Y-%m-%d')
                        days_to_hire = (hired - applied).days
                        dept_metrics[department]['times'].append(days_to_hire)
                    except:
                        pass
        
        # Calculate averages and find fastest/slowest
        dept_performance = {}
        for dept, metrics in dept_metrics.items():
            if metrics['times']:
                avg_time = sum(metrics['times']) / len(metrics['times'])
                dept_performance[dept] = avg_time
        
        if dept_performance:
            fastest_dept = min(dept_performance.items(), key=lambda x: x[1])
            slowest_dept = max(dept_performance.items(), key=lambda x: x[1])
            
            return f"Department Interview Efficiency: Fastest: {fastest_dept[0]} ({fastest_dept[1]:.1f} days avg), Slowest: {slowest_dept[0]} ({slowest_dept[1]:.1f} days avg). Performance by dept: {dict(dept_performance)}"
        else:
            return "Department Interview Efficiency: Insufficient data for timing analysis"
    
    except Exception as e:
        return f"Error analyzing department insights: {str(e)}"

def get_enhanced_hiring_predictions() -> str:
    """Get predictive insights for future hiring needs and timelines"""
    from collections import defaultdict
    from datetime import timedelta
    
    try:
        candidates = load_json_data("candidates.json")
        jobs = load_json_data("jobs.json")
        
        # Calculate average time to hire
        hiring_times = []
        for candidate in candidates:
            if candidate.get('status') == 'Hired' and candidate.get('applied_date') and candidate.get('hired_date'):
                try:
                    applied = datetime.strptime(candidate['applied_date'], '%Y-%m-%d')
                    hired = datetime.strptime(candidate['hired_date'], '%Y-%m-%d')
                    days_to_hire = (hired - applied).days
                    hiring_times.append(days_to_hire)
                except:
                    pass
        
        if hiring_times:
            avg_days = sum(hiring_times) / len(hiring_times)
            avg_months = avg_days / 30
            
            # Predict time to hire X employees
            prediction_text = f"Hiring Predictions: Average time to hire: {avg_days:.1f} days ({avg_months:.1f} months). "
            prediction_text += f"To hire 20 employees at current pace: {20 * avg_months:.1f} months. "
            prediction_text += f"Current hiring velocity: {len([c for c in candidates if c.get('status') == 'Hired'])} hired total"
            
            return prediction_text
        else:
            return "Hiring Predictions: Insufficient historical data for accurate predictions"
    
    except Exception as e:
        return f"Error generating hiring predictions: {str(e)}"

def get_enhanced_top_performers() -> str:
    """Get insights on top performing team members and peak hiring periods"""
    from collections import defaultdict
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Track performance by status updaters
        updater_performance = defaultdict(lambda: {'hires': 0, 'updates': 0})
        
        for candidate in candidates:
            updater = candidate.get('status_updated_by', 'Unknown')
            updater_performance[updater]['updates'] += 1
            
            if candidate.get('status') == 'Hired':
                updater_performance[updater]['hires'] += 1
        
        # Find top performer
        top_performer = ("Unknown", 0)
        for updater, metrics in updater_performance.items():
            if metrics['hires'] > top_performer[1] and updater != 'System (CV Upload)':
                top_performer = (updater, metrics['hires'])
        
        return f"Top Performers: Top hirer: {top_performer[0]} ({top_performer[1]} successful hires). Performance breakdown: {dict(updater_performance)}"
    
    except Exception as e:
        return f"Error analyzing top performers: {str(e)}"

def get_enhanced_salary_trends() -> str:
    """Get comprehensive salary trend analysis with market positioning"""
    from statistics import mean, median
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Collect salary data for hired candidates
        salaries = []
        market_comparisons = []
        benefits = []
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired' and candidate.get('final_salary'):
                salaries.append(candidate['final_salary'])
                
                if candidate.get('benefits_package'):
                    benefits.append(candidate['benefits_package'])
                
                if candidate.get('market_comparison', {}).get('competitiveness'):
                    market_comparisons.append(candidate['market_comparison']['competitiveness'])
        
        if salaries:
            avg_salary = mean(salaries)
            median_salary = median(salaries)
            min_salary = min(salaries)
            max_salary = max(salaries)
            
            # Market competitiveness
            above_market = market_comparisons.count('Above Market')
            below_market = market_comparisons.count('Below Market')
            at_market = market_comparisons.count('Market Rate')
            
            trend_text = f"Salary Trends: Average offered: ${avg_salary:,.0f}, Median: ${median_salary:,.0f}, Range: ${min_salary:,.0f}-${max_salary:,.0f}. "
            trend_text += f"Market positioning: {above_market} above market, {at_market} at market, {below_market} below market rates"
            
            return trend_text
        else:
            return "Salary Trends: No salary data available for analysis"
    
    except Exception as e:
        return f"Error analyzing salary trends: {str(e)}"

def get_enhanced_onboarding_insights() -> str:
    """Get detailed onboarding process analysis and bottleneck identification"""
    from collections import defaultdict
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Onboarding status analysis
        onboarding_status = defaultdict(int)
        completion_delays = []
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired':
                status = candidate.get('onboarding_status', 'Unknown')
                onboarding_status[status] += 1
                
                # Check for delays
                if status == 'Delayed':
                    completion_delays.append(candidate.get('name', 'Unknown'))
        
        # Identify bottlenecks
        total_hired = sum(onboarding_status.values())
        delayed_pct = (onboarding_status['Delayed'] / total_hired * 100) if total_hired > 0 else 0
        
        insights = f"Onboarding Insights: Status breakdown: {dict(onboarding_status)}. "
        insights += f"Delay rate: {delayed_pct:.1f}%. "
        
        if delayed_pct > 20:
            insights += "Bottleneck: High delay rate indicates process inefficiencies"
        else:
            insights += "Onboarding process performing well"
        
        return insights
    
    except Exception as e:
        return f"Error analyzing onboarding insights: {str(e)}"

def get_enhanced_probation_insights() -> str:
    """Get probation period performance analysis and improvement areas"""
    from collections import defaultdict
    
    try:
        candidates = load_json_data("candidates.json")
        jobs = load_json_data("jobs.json")
        
        # Create job lookup
        job_lookup = {job['job_id']: job for job in jobs}
        
        # Probation analysis by department
        dept_probation = defaultdict(lambda: {'total': 0, 'passed': 0, 'under_review': 0, 'ratings': []})
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired' and candidate.get('probation_status'):
                job_id = candidate.get('job_id', '1')
                job = job_lookup.get(job_id, {})
                department = job.get('department', 'Unknown')
                
                probation_status = candidate.get('probation_status')
                performance_rating = candidate.get('performance_rating')
                
                dept_probation[department]['total'] += 1
                
                if probation_status == 'Passed':
                    dept_probation[department]['passed'] += 1
                elif probation_status == 'Under Review':
                    dept_probation[department]['under_review'] += 1
                
                if performance_rating:
                    dept_probation[department]['ratings'].append(performance_rating)
        
        # Find department needing improvement
        worst_dept = None
        worst_pass_rate = 100
        
        for dept, metrics in dept_probation.items():
            if metrics['total'] > 0:
                pass_rate = (metrics['passed'] / metrics['total']) * 100
                if pass_rate < worst_pass_rate:
                    worst_pass_rate = pass_rate
                    worst_dept = dept
        
        insights = f"Probation Insights: Department performance: {dict(dept_probation)}. "
        if worst_dept:
            insights += f"Needs improvement: {worst_dept} (pass rate: {worst_pass_rate:.1f}%)"
        
        return insights
    
    except Exception as e:
        return f"Error analyzing probation insights: {str(e)}"

def get_enhanced_market_salary_comparison() -> str:
    """Get comprehensive market salary comparison with competitiveness analysis"""
    from statistics import mean
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Analyze market positioning
        our_salaries = []
        market_salaries = []
        competitiveness_breakdown = {'Above Market': 0, 'Market Rate': 0, 'Below Market': 0}
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired' and candidate.get('market_comparison'):
                market_data = candidate['market_comparison']
                
                our_salaries.append(market_data.get('our_offer', 0))
                market_salaries.append(market_data.get('market_average', 0))
                
                competitiveness = market_data.get('competitiveness', 'Unknown')
                if competitiveness in competitiveness_breakdown:
                    competitiveness_breakdown[competitiveness] += 1
        
        if our_salaries and market_salaries:
            our_avg = mean(our_salaries)
            market_avg = mean(market_salaries)
            difference = ((our_avg - market_avg) / market_avg) * 100
            
            # Overall competitiveness
            total_positions = sum(competitiveness_breakdown.values())
            above_market_pct = (competitiveness_breakdown['Above Market'] / total_positions) * 100
            
            comparison_text = f"Market Salary Comparison: Our average: ${our_avg:,.0f}, Market average: ${market_avg:,.0f} "
            comparison_text += f"({difference:+.1f}% vs market). Breakdown: {competitiveness_breakdown}. "
            
            if above_market_pct > 50:
                comparison_text += "Our salaries are competitive with market rates"
            elif above_market_pct < 30:
                comparison_text += "Our salaries are below market - may impact talent acquisition"
            else:
                comparison_text += "Mixed competitiveness - some positions above/below market"
            
            return comparison_text
        else:
            return "Market Salary Comparison: No market comparison data available"
    
    except Exception as e:
        return f"Error analyzing market salary comparison: {str(e)}"

def comprehensive_hiring_analysis() -> str:
    """Get complete hiring analysis including all metrics, visualizations, and market insights"""
    try:
        # Generate comprehensive analysis
        analysis_parts = []
        
        # Core metrics
        analysis_parts.append("=== COMPREHENSIVE HIRING ANALYSIS ===")
        analysis_parts.append(get_enhanced_hiring_success_rate())
        analysis_parts.append(get_enhanced_monthly_insights())
        analysis_parts.append(get_enhanced_department_insights())
        analysis_parts.append(get_enhanced_hiring_predictions())
        analysis_parts.append(get_enhanced_salary_trends())
        analysis_parts.append(get_enhanced_market_salary_comparison())
        analysis_parts.append(get_enhanced_onboarding_insights())
        analysis_parts.append(get_enhanced_probation_insights())
        
        # Create visualizations
        try:
            chart_msg = create_hiring_trend_chart()
            analysis_parts.append(f"📊 {chart_msg}")
        except:
            pass
        
        try:
            pie_msg = create_pie_chart("status_distribution")
            analysis_parts.append(f"📊 {pie_msg}")
        except:
            pass
        
        return "\n\n".join(analysis_parts)
    
    except Exception as e:
        return f"Error generating comprehensive analysis: {str(e)}"

def create_hiring_trend_chart() -> str:
    """Create hiring trend visualization"""
    import matplotlib.pyplot as plt
    from collections import defaultdict
    from datetime import timedelta
    
    try:
        candidates = load_json_data("candidates.json")
        
        # Monthly hiring data
        monthly_data = defaultdict(int)
        
        for candidate in candidates:
            if candidate.get('status') == 'Hired' and candidate.get('hired_date'):
                try:
                    hired_date = datetime.strptime(candidate['hired_date'], '%Y-%m-%d')
                    month_key = hired_date.strftime('%Y-%m')
                    monthly_data[month_key] += 1
                except:
                    pass
        
        if monthly_data:
            months = sorted(monthly_data.keys())
            counts = [monthly_data[month] for month in months]
            
            plt.figure(figsize=(12, 6))
            plt.plot(months, counts, marker='o', linewidth=2, markersize=8)
            plt.title('Monthly Hiring Trends', fontsize=16, fontweight='bold')
            plt.xlabel('Month', fontsize=12)
            plt.ylabel('Number of Hires', fontsize=12)
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            filepath = 'db/monthly_hiring_trends.png'
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            return f"Monthly hiring trends chart created: ![Monthly Hiring Trends]({filepath})"
        else:
            return "No hiring data available for trend chart"
            
    except Exception as e:
        return f"Error creating hiring trend chart: {str(e)}"
