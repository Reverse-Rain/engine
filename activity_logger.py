"""
Enhanced Activity Logger for AION HR System
Tracks all user activities across the application
"""

import json
import os
import datetime
from typing import Dict, List, Any, Optional
import threading


class ActivityLogger:
    def __init__(self, db_folder: str = "./db"):
        self.db_folder = db_folder
        self.activity_file = os.path.join(db_folder, "activity_log.json")
        self.lock = threading.Lock()
        
        # Ensure the db folder exists
        os.makedirs(db_folder, exist_ok=True)
        
        # Initialize activity log if it doesn't exist
        if not os.path.exists(self.activity_file):
            self._write_activities([])
    
    def _write_activities(self, activities: List[Dict]):
        """Write activities to file with error handling"""
        try:
            with open(self.activity_file, 'w', encoding='utf-8') as f:
                json.dump(activities, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error writing activities: {e}")
    
    def _read_activities(self) -> List[Dict]:
        """Read activities from file with error handling"""
        try:
            if os.path.exists(self.activity_file):
                with open(self.activity_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error reading activities: {e}")
        return []
    
    def log_activity(self, 
                    activity_type: str,
                    description: str, 
                    user: str = "system",
                    details: Optional[Dict] = None,
                    entity_id: Optional[str] = None,
                    entity_type: Optional[str] = None):
        """
        Log a new activity
        
        Args:
            activity_type: Type of activity (e.g., 'candidate_created', 'job_posted', 'interview_scheduled')
            description: Human-readable description of the activity
            user: Username who performed the action
            details: Additional details about the activity
            entity_id: ID of the entity involved (candidate ID, job ID, etc.)
            entity_type: Type of entity (candidate, job, user, etc.)
        """
        activity = {
            "id": self._generate_activity_id(),
            "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "activity_type": activity_type,
            "description": description,
            "user": user,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "details": details or {},
            "date": datetime.datetime.now().strftime('%Y-%m-%d'),
            "time": datetime.datetime.now().strftime('%H:%M:%S')
        }
        
        # Thread-safe writing
        with self.lock:
            activities = self._read_activities()
            activities.append(activity)
            
            # Keep only last 1000 activities to prevent file from growing too large
            if len(activities) > 1000:
                activities = activities[-1000:]
            
            self._write_activities(activities)
    
    def get_recent_activities(self, limit: int = 50, days: int = 7) -> List[Dict]:
        """Get recent activities within specified days"""
        activities = self._read_activities()
        
        # Filter by date
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        recent_activities = []
        
        for activity in reversed(activities):  # Most recent first
            try:
                activity_date = datetime.datetime.strptime(activity['timestamp'], '%Y-%m-%d %H:%M:%S')
                if activity_date >= cutoff_date:
                    recent_activities.append(activity)
                    if len(recent_activities) >= limit:
                        break
            except Exception:
                continue
        
        return recent_activities
    
    def get_todays_activities(self) -> List[Dict]:
        """Get activities from today only"""
        activities = self._read_activities()
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        todays_activities = []
        for activity in reversed(activities):
            if activity.get('date') == today:
                todays_activities.append(activity)
        
        return todays_activities
    
    def get_activities_by_type(self, activity_type: str, limit: int = 20) -> List[Dict]:
        """Get activities of a specific type"""
        activities = self._read_activities()
        filtered = [a for a in reversed(activities) if a.get('activity_type') == activity_type]
        return filtered[:limit]
    
    def get_activities_by_user(self, user: str, limit: int = 20) -> List[Dict]:
        """Get activities by a specific user"""
        activities = self._read_activities()
        filtered = [a for a in reversed(activities) if a.get('user') == user]
        return filtered[:limit]
    
    def _generate_activity_id(self) -> str:
        """Generate a unique activity ID"""
        return f"act_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


# Global activity logger instance
activity_logger = ActivityLogger()


# Convenience functions for common activities
def log_candidate_activity(action: str, candidate_id: str, candidate_name: str, user: str, details: Dict = None):
    """Log candidate-related activity"""
    activity_logger.log_activity(
        activity_type=f"candidate_{action}",
        description=f"Candidate {candidate_name} (ID: {candidate_id}) {action}",
        user=user,
        entity_id=candidate_id,
        entity_type="candidate",
        details=details
    )


def log_job_activity(action: str, job_id: str, job_title: str, user: str, details: Dict = None):
    """Log job-related activity"""
    activity_logger.log_activity(
        activity_type=f"job_{action}",
        description=f"Job '{job_title}' (ID: {job_id}) {action}",
        user=user,
        entity_id=job_id,
        entity_type="job",
        details=details
    )


def log_interview_activity(action: str, candidate_id: str, candidate_name: str, interview_date: str, user: str, details: Dict = None):
    """Log interview-related activity"""
    activity_logger.log_activity(
        activity_type=f"interview_{action}",
        description=f"Interview {action} for {candidate_name} (ID: {candidate_id}) on {interview_date}",
        user=user,
        entity_id=candidate_id,
        entity_type="interview",
        details=details
    )


def log_onboarding_activity(action: str, candidate_id: str, candidate_name: str, user: str, details: Dict = None):
    """Log onboarding-related activity"""
    activity_logger.log_activity(
        activity_type=f"onboarding_{action}",
        description=f"Onboarding {action} for {candidate_name} (ID: {candidate_id})",
        user=user,
        entity_id=candidate_id,
        entity_type="onboarding",
        details=details
    )


def log_user_activity(action: str, target_user: str, admin_user: str, details: Dict = None):
    """Log user management activity"""
    activity_logger.log_activity(
        activity_type=f"user_{action}",
        description=f"User {target_user} {action} by {admin_user}",
        user=admin_user,
        entity_id=target_user,
        entity_type="user",
        details=details
    )


def log_system_activity(action: str, description: str, user: str = "system", details: Dict = None):
    """Log system-level activity"""
    activity_logger.log_activity(
        activity_type=f"system_{action}",
        description=description,
        user=user,
        entity_type="system",
        details=details
    )


def log_chat_activity(user: str, query: str, response_type: str = "assistant"):
    """Log chatbot interactions"""
    activity_logger.log_activity(
        activity_type="chat_interaction",
        description=f"User {user} asked: {query[:100]}..." if len(query) > 100 else f"User {user} asked: {query}",
        user=user,
        entity_type="chat",
        details={"query": query, "response_type": response_type}
    )


def log_analytics_activity(user: str, analysis_type: str, details: Dict = None):
    """Log analytics usage"""
    activity_logger.log_activity(
        activity_type="analytics_view",
        description=f"User {user} viewed {analysis_type} analytics",
        user=user,
        entity_type="analytics",
        details=details
    )


# Migration function to populate activities from existing data
def migrate_existing_activities():
    """Migrate existing candidate and job data to activity log"""
    try:
        db_folder = os.path.join(os.path.dirname(__file__), 'db')
        
        # Migrate candidates
        candidate_file = os.path.join(db_folder, 'candidates.json')
        if os.path.exists(candidate_file):
            with open(candidate_file, 'r') as f:
                candidates = json.load(f)
            
            for candidate in candidates:
                # Log candidate creation
                if candidate.get('applied_date'):
                    activity_logger.log_activity(
                        activity_type="candidate_created",
                        description=f"Candidate {candidate.get('name', 'Unknown')} (ID: {candidate.get('id', 'Unknown')}) applied",
                        user=candidate.get('email', 'Unknown'),
                        entity_id=candidate.get('id'),
                        entity_type="candidate",
                        details={"migrated": True, "original_date": candidate.get('applied_date')}
                    )
                
                # Log status changes if updated
                if candidate.get('updated_at'):
                    activity_logger.log_activity(
                        activity_type="candidate_updated",
                        description=f"Candidate {candidate.get('name', 'Unknown')} (ID: {candidate.get('id', 'Unknown')}) status updated to {candidate.get('status', 'Unknown')}",
                        user=candidate.get('updated_by', 'Unknown'),
                        entity_id=candidate.get('id'),
                        entity_type="candidate",
                        details={"migrated": True, "status": candidate.get('status')}
                    )
        
        # Migrate jobs
        job_file = os.path.join(db_folder, 'jobs.json')
        if os.path.exists(job_file):
            with open(job_file, 'r') as f:
                jobs = json.load(f)
            
            for job in jobs:
                if job.get('posted_at'):
                    activity_logger.log_activity(
                        activity_type="job_posted",
                        description=f"Job '{job.get('job_title', 'Unknown')}' posted",
                        user=job.get('job_posted_by', 'Unknown'),
                        entity_id=job.get('id'),
                        entity_type="job",
                        details={"migrated": True, "department": job.get('department')}
                    )
        
        print("✅ Activity migration completed successfully")
        
    except Exception as e:
        print(f"⚠️ Error during activity migration: {e}")


if __name__ == "__main__":
    # Run migration if called directly
    migrate_existing_activities()
