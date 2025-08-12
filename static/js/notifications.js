// Notification System JavaScript
class NotificationSystem {
    constructor() {
        this.notifications = [];
        this.container = null;
        this.checkInterval = null;
    this.audioEnabled = false;
    this.audioCtx = null;
    this.customAudioElement = null;
    this._audioUnlockHandler = this._audioUnlockHandler.bind(this);
    this.isApprovalsPage = window.location.pathname.startsWith('/my_approvals');
    this.firstFetchDone = false; // to suppress sound on initial historical load
    this.seenSoundIds = new Set(); // ids we've already used to trigger a sound
    this.lastFetchTime = 0;
        this.init();
    }

    init() {
        this.createContainer();
        this.startPeriodicCheck();
        this.bindEvents();
    this.prepareAudio();
    }

    createContainer() {
        // Create notification container
        this.container = document.createElement('div');
        this.container.className = 'notification-container';
        this.container.id = 'notification-container';
        document.body.appendChild(this.container);
    }

    async fetchNotifications() {
        try {
            console.log('Fetching notifications...');
            const response = await fetch('/api/notifications');
            console.log('Response status:', response.status);
            if (response.ok) {
                const data = await response.json();
                console.log('Notifications data:', data);
                return data.notifications || [];
            } else {
                console.error('Failed to fetch notifications, status:', response.status);
            }
        } catch (error) {
            console.error('Error fetching notifications:', error);
        }
        return [];
    }

    async markAsRead(notificationId) {
        try {
            await fetch(`/api/notifications/${notificationId}/mark_read`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    createNotificationElement(notification) {
        const notificationEl = document.createElement('div');
    notificationEl.className = `notification-popup white ${notification.priority === 'high' ? 'high-priority' : ''}`;
        notificationEl.setAttribute('data-notification-id', notification.id);

        const timeAgo = this.formatTimeAgo(notification.timestamp);
        const candidateName = notification.candidate_name || 'Unknown';
        const position = notification.position || 'Unknown Position';

    const needsDecision = notification.action_required && ['shortlist_for_approval','candidate_selected','dept_approved_notify_hr','reminder_pending_dept_selection','reminder_pending_operations_hire'].includes(notification.type);
        notificationEl.innerHTML = `
            <div class="notification-header">
                <h4 class="notification-title">
                    ${notification.type.replace(/_/g,' ').toUpperCase()}
                </h4>
                <button class="notification-close" onclick="notificationSystem.dismissNotification(${notification.id})">&times;</button>
            </div>
            <div class="notification-message">${notification.message}</div>
            <div class="notification-actions">
        <a href="/candidate/${notification.candidate_id}" class="notification-action-btn primary" data-mark-read="${notification.id}">View</a>
                ${needsDecision ? `<form method='POST' action='/approve_candidate' style='display:inline;'>
                    <input type='hidden' name='candidate_id' value='${notification.candidate_id}' />
                    <input type='hidden' name='action' value='approve' />
            <button type='submit' class='notification-action-btn approve-btn' data-mark-read='${notification.id}'>Approve</button>
                </form>`:''}
                ${needsDecision ? `<form method='POST' action='/approve_candidate' style='display:inline;'>
                    <input type='hidden' name='candidate_id' value='${notification.candidate_id}' />
                    <input type='hidden' name='action' value='reject' />
            <button type='submit' class='notification-action-btn reject-btn' data-mark-read='${notification.id}'>Reject</button>
                </form>`:''}
                <button class="notification-action-btn" onclick="notificationSystem.dismissNotification(${notification.id})">Dismiss</button>
            </div>
            <div class="notification-meta">
                <span><strong>${candidateName}</strong> - ${position}</span>
                <span>${timeAgo}</span>
            </div>`;

        return notificationEl;
    }

    showNotification(notification) {
        // Check if notification already exists
        const existingNotification = document.querySelector(`[data-notification-id="${notification.id}"]`);
        if (existingNotification) {
            return;
        }
    const notificationEl = this.createNotificationElement(notification);
    this.container.appendChild(notificationEl);

    // Mark as read immediately so it doesn't repeat
    this.markAsRead(notification.id);

        // Auto-dismiss after 15 seconds for non-critical notifications
        if (notification.priority !== 'high') {
            setTimeout(() => {
                this.dismissNotification(notification.id);
            }, 15000);
        }

        // Add to internal notifications array
        this.notifications.push(notification);
    }

    async dismissNotification(notificationId) {
        const notificationEl = document.querySelector(`[data-notification-id="${notificationId}"]`);
        if (notificationEl) {
            notificationEl.classList.add('fade-out');
            setTimeout(() => {
                if (notificationEl.parentNode) {
                    notificationEl.parentNode.removeChild(notificationEl);
                }
            }, 500);

            // Mark as read in backend
            await this.markAsRead(notificationId);

            // Remove from internal array
            this.notifications = this.notifications.filter(n => n.id !== notificationId);
        }
    }

    async checkForNewNotifications() {
        console.log('Checking for new notifications...');
        const newNotifications = await this.fetchNotifications();
        console.log('Fetched notifications:', newNotifications);
        const toShow = [];
        const nowMs = Date.now();
        for (const notification of newNotifications) {
            const exists = this.notifications.some(n => n.id === notification.id);
            if (!exists) {
                this.notifications.push(notification); // track regardless of popup
                if (this.isApprovalsPage) {
                    // On approvals page, just mark read silently
                    this.markAsRead(notification.id);
                } else {
                    toShow.push(notification);
                }
            }
        }
        if (!this.isApprovalsPage) {
            toShow.forEach(n => this.showNotification(n));
            // Sound criteria: after first fetch, have at least one truly new & fresh notification not sounded before
            if (this.firstFetchDone && toShow.length) {
                const freshNew = toShow.filter(n => {
                    const t = new Date(n.timestamp).getTime();
                    // fresh if within 12s and not previously sounded
                    return (nowMs - t) >= 0 && (nowMs - t) < 12000 && !this.seenSoundIds.has(n.id);
                });
                if (freshNew.length) {
                    this.playNotificationSound();
                    freshNew.forEach(n => this.seenSoundIds.add(n.id));
                }
            }
        }
        this.firstFetchDone = true;
        this.lastFetchTime = nowMs;
    }

    startPeriodicCheck() {
        // Check for new notifications every 10 seconds
        this.checkInterval = setInterval(() => {
            this.checkForNewNotifications();
        }, 10000);

        // Initial check
        this.checkForNewNotifications();
    }

    stopPeriodicCheck() {
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
        }
    }

    playNotificationSound() {
        if (!this.audioEnabled) return; // not yet unlocked by user gesture
        if (this._lastSoundAt && Date.now() - this._lastSoundAt < 1200) return; // throttle
        this._lastSoundAt = Date.now();

        // Custom element path
        if (this.customAudioElement) {
            try {
                this.customAudioElement.currentTime = 0;
                this.customAudioElement.play();
                return;
            } catch (e) { /* fallback below */ }
        }

        // Synthesize tri-tone using unlocked context
        try {
            const ctx = this.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            this.audioCtx = ctx;
            const now = ctx.currentTime;
            const master = ctx.createGain();
            master.gain.setValueAtTime(0.28, now);
            master.connect(ctx.destination);
            const freqs = [1046.5, 1318.5, 1568]; // C6 E6 G#6
            freqs.forEach((f,i) => {
                const osc = ctx.createOscillator();
                const g = ctx.createGain();
                osc.type = 'sine';
                osc.frequency.setValueAtTime(f, now);
                osc.frequency.exponentialRampToValueAtTime(f*0.92, now + 0.25);
                g.gain.setValueAtTime(0.0001, now);
                g.gain.exponentialRampToValueAtTime(0.35/(i+1), now + 0.015 + i*0.01);
                g.gain.exponentialRampToValueAtTime(0.0001, now + 0.45 + i*0.02);
                osc.connect(g); g.connect(master);
                osc.start(now);
                osc.stop(now + 0.5);
            });
        } catch (err) {
            console.log('Notification sound fallback failed');
        }
    }

    prepareAudio() {
        // Attach one-time user gesture unlock
        ['click','keydown','pointerdown','touchstart'].forEach(ev => {
            window.addEventListener(ev, this._audioUnlockHandler, { once: true, passive: true });
        });
    }

    async _audioUnlockHandler() {
        try {
            this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            // Attempt to load custom file
            const url = '/static/sounds/notify.mp3';
            const res = await fetch(url, { method: 'GET' });
            if (res.ok && res.headers.get('content-type') && res.headers.get('content-type').includes('audio')) {
                const blob = await res.blob();
                const objUrl = URL.createObjectURL(blob);
                const el = new Audio(objUrl);
                el.volume = 0.4;
                this.customAudioElement = el;
            }
            this.audioEnabled = true;
            // Removed automatic confirmation sound so normal UI clicks (navbar, charts) don't trigger audio.
            // Sound will now only play when an actual new notification arrives per criteria in checkForNewNotifications().
        } catch (e) {
            this.audioEnabled = true; // still allow synthesized fallback
        }
    }

    formatTimeAgo(timestamp) {
        const now = new Date();
        const notificationTime = new Date(timestamp);
        const diffInSeconds = Math.floor((now - notificationTime) / 1000);

        if (diffInSeconds < 60) {
            return 'Just now';
        } else if (diffInSeconds < 3600) {
            const minutes = Math.floor(diffInSeconds / 60);
            return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
        } else if (diffInSeconds < 86400) {
            const hours = Math.floor(diffInSeconds / 3600);
            return `${hours} hour${hours === 1 ? '' : 's'} ago`;
        } else {
            const days = Math.floor(diffInSeconds / 86400);
            return `${days} day${days === 1 ? '' : 's'} ago`;
        }
    }

    bindEvents() {
        // Clean up on page unload
        window.addEventListener('beforeunload', () => {
            this.stopPeriodicCheck();
        });

        // Handle visibility change (pause when tab is not active)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.stopPeriodicCheck();
            } else {
                this.startPeriodicCheck();
            }
        });

        // Delegate mark-read on clicks with data-mark-read
        document.body.addEventListener('click', async (e) => {
            const target = e.target;
            if (target && target.getAttribute && target.getAttribute('data-mark-read')) {
                const nid = target.getAttribute('data-mark-read');
                // mark read immediately to prevent future polling duplication
                await this.markAsRead(nid);
                const el = document.querySelector(`[data-notification-id="${nid}"]`);
                if (el) el.parentNode.removeChild(el);
            }
        });
    }

    // Public method to manually trigger notification check
    refresh() {
        this.checkForNewNotifications();
    }

    // Get current notification count
    getNotificationCount() {
        return this.notifications.length;
    }

    // Clear all notifications
    clearAll() {
        this.notifications.forEach(notification => {
            this.dismissNotification(notification.id);
        });
    }
}

// Initialize notification system when DOM is ready
let notificationSystem;

document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, initializing notification system...');
    // Only initialize if user is logged in (has role cookie)
    const userRole = getCookie('role');
    console.log('User role:', userRole);
    if (userRole) {
        console.log('Initializing notification system for role:', userRole);
        notificationSystem = new NotificationSystem();
        console.log('Notification system initialized');
    } else {
        console.log('No user role found, skipping notification system');
    }
});

// Utility function to get cookie value
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

// Make notification system available globally
window.notificationSystem = notificationSystem;
