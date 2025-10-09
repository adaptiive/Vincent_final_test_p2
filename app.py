from flask import Flask, render_template, jsonify, request, session
import speedtest
import threading
import time
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'wifi_speed_test_secret_key_2024'

# Global variable to store the latest speed test results
latest_results = {
    'download': 0,
    'upload': 0,
    'ping': 0,
    'timestamp': None,
    'testing': False,
    'status': 'Ready'
}

# Historical data storage (in production, use a database)
test_history = []

# User roles configuration
USER_ROLES = {
    'home_user': {
        'name': 'Home User',
        'description': 'Simple speed testing for personal use',
        'features': ['basic_test', 'simple_results']
    },
    'it_admin': {
        'name': 'IT Administrator', 
        'description': 'Network management and monitoring',
        'features': ['basic_test', 'detailed_results', 'history', 'diagnostics']
    },
    'isp_support': {
        'name': 'ISP Customer Support',
        'description': 'Customer support and troubleshooting',
        'features': ['basic_test', 'detailed_results', 'diagnostics', 'report_sharing']
    }
}

def run_speed_test(user_role='home_user'):
    """Run speed test in background thread.

    Accepts user_role to avoid accessing Flask session from a background thread.
    """
    global latest_results, test_history
    
    try:
        latest_results['testing'] = True
        latest_results['status'] = 'Finding best server...'
        
        # Configure speedtest with timeout and faster settings
        st = speedtest.Speedtest(timeout=10)
        
        # Get best server (faster server selection)
        st.get_best_server()
        
        # Test download speed (with smaller test size for faster results)
        latest_results['status'] = 'Testing download speed...'
        download_speed = st.download(threads=1) / 1_000_000  # Single thread, convert to Mbps
        latest_results['download'] = round(download_speed, 2)
        
        # Test upload speed (with smaller test size for faster results)
        latest_results['status'] = 'Testing upload speed...'
        upload_speed = st.upload(threads=1) / 1_000_000  # Single thread, convert to Mbps
        latest_results['upload'] = round(upload_speed, 2)
        
        # Get ping
        latest_results['status'] = 'Measuring ping...'
        latest_results['ping'] = round(st.results.ping, 2)
        
        # Update timestamp
        latest_results['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
        latest_results['status'] = 'Complete'
        
        # Store in history (do not access session inside thread)
        test_history.append({
            'timestamp': latest_results['timestamp'],
            'download': latest_results['download'],
            'upload': latest_results['upload'],
            'ping': latest_results['ping'],
            'server': st.results.server['name'] if getattr(st.results, 'server', None) else 'Unknown',
            'user_role': user_role
        })
        
        # Keep only last 50 tests
        if len(test_history) > 50:
            test_history.pop(0)
        
    except Exception as e:
        print(f"Error during speed test: {e}")
        latest_results['download'] = 0
        latest_results['upload'] = 0
        latest_results['ping'] = 0
        latest_results['status'] = f'Error: {str(e)}'
    
    finally:
        latest_results['testing'] = False

@app.route('/')
def index():
    """Main page"""
    user_role = session.get('user_role', None)
    return render_template('index.html', user_role=user_role, roles=USER_ROLES)

@app.route('/set-role', methods=['POST'])
def set_role():
    """Set user role"""
    role = request.json.get('role')
    if role in USER_ROLES:
        session['user_role'] = role
        return jsonify({'status': 'success', 'role': role})
    return jsonify({'status': 'error', 'message': 'Invalid role'})

@app.route('/get-role')
def get_role():
    """Get current user role"""
    role = session.get('user_role', None)
    return jsonify({'role': role, 'config': USER_ROLES.get(role) if role else None})

@app.route('/start-test')
def start_test():
    """Start speed test"""
    if not latest_results['testing']:
        role = session.get('user_role', 'home_user')
        thread = threading.Thread(target=run_speed_test, args=(role,))
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'started'})
    else:
        return jsonify({'status': 'already_running'})

@app.route('/results')
def get_results():
    """Get current results"""
    user_role = session.get('user_role', 'home_user')
    result = latest_results.copy()
    
    # Add role-specific data
    if user_role == 'it_admin' or user_role == 'isp_support':
        result['detailed'] = True
        result['server_info'] = 'Available after test'
    
    return jsonify(result)

@app.route('/history')
def get_history():
    """Get test history (IT Admin and ISP Support only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role not in ['it_admin', 'isp_support']:
        return jsonify({'error': 'Access denied'}), 403
    
    # Filter history by time range if requested
    days = request.args.get('days', 7, type=int)
    cutoff_date = datetime.now() - timedelta(days=days)
    
    filtered_history = []
    for test in test_history:
        test_date = datetime.strptime(test['timestamp'], '%Y-%m-%d %H:%M:%S')
        if test_date >= cutoff_date:
            filtered_history.append(test)
    
    return jsonify({'history': filtered_history, 'total_tests': len(filtered_history)})

@app.route('/diagnostics')
def get_diagnostics():
    """Get network diagnostics (IT Admin and ISP Support only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role not in ['it_admin', 'isp_support']:
        return jsonify({'error': 'Access denied'}), 403
    
    # Basic network diagnostics
    diagnostics = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'tests_today': len([t for t in test_history if t['timestamp'].startswith(time.strftime('%Y-%m-%d'))]),
        'avg_download': round(sum([t['download'] for t in test_history[-10:]]) / len(test_history[-10:]), 2) if test_history else 0,
        'avg_upload': round(sum([t['upload'] for t in test_history[-10:]]) / len(test_history[-10:]), 2) if test_history else 0,
        'avg_ping': round(sum([t['ping'] for t in test_history[-10:]]) / len(test_history[-10:]), 2) if test_history else 0,
    }
    
    return jsonify(diagnostics)

@app.route('/generate-report')
def generate_report():
    """Generate a shareable report (ISP Support only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role != 'isp_support':
        return jsonify({'error': 'Access denied'}), 403
    
    if not latest_results['timestamp']:
        return jsonify({'error': 'No test results available'})
    
    report = {
        'report_id': f"REPORT_{int(time.time())}",
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'test_results': {
            'download_mbps': latest_results['download'],
            'upload_mbps': latest_results['upload'],
            'ping_ms': latest_results['ping'],
            'test_timestamp': latest_results['timestamp']
        },
        'summary': f"Customer speed test results: {latest_results['download']} Mbps down, {latest_results['upload']} Mbps up, {latest_results['ping']} ms ping"
    }
    
    return jsonify(report)

@app.route('/clear-history', methods=['POST'])
def clear_history():
    """Clear test history (IT Admin only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role != 'it_admin':
        return jsonify({'error': 'Access denied'}), 403
    
    global test_history
    test_history.clear()
    return jsonify({'status': 'success', 'message': 'History cleared'})

@app.route('/export-data')
def export_data():
    """Export test data (IT Admin and ISP Support only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role not in ['it_admin', 'isp_support']:
        return jsonify({'error': 'Access denied'}), 403
    
    export_data = {
        'export_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'user_role': user_role,
        'test_history': test_history,
        'latest_results': latest_results,
        'total_tests': len(test_history)
    }
    
    return jsonify(export_data)

@app.route('/network-status')
def network_status():
    """Get network status overview (IT Admin and ISP Support only)"""
    user_role = session.get('user_role', 'home_user')
    
    if user_role not in ['it_admin', 'isp_support']:
        return jsonify({'error': 'Access denied'}), 403
    
    # Calculate network health indicators
    recent_tests = test_history[-5:] if test_history else []
    
    if recent_tests:
        avg_download = sum(t['download'] for t in recent_tests) / len(recent_tests)
        avg_upload = sum(t['upload'] for t in recent_tests) / len(recent_tests)
        avg_ping = sum(t['ping'] for t in recent_tests) / len(recent_tests)
        
        # Simple health scoring
        download_health = 'Good' if avg_download > 25 else 'Fair' if avg_download > 10 else 'Poor'
        upload_health = 'Good' if avg_upload > 5 else 'Fair' if avg_upload > 2 else 'Poor'
        ping_health = 'Good' if avg_ping < 50 else 'Fair' if avg_ping < 100 else 'Poor'
    else:
        download_health = upload_health = ping_health = 'No Data'
        avg_download = avg_upload = avg_ping = 0
    
    status = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'overall_health': 'Good' if all(h == 'Good' for h in [download_health, upload_health, ping_health]) else 'Fair',
        'download_health': download_health,
        'upload_health': upload_health,
        'ping_health': ping_health,
        'recent_avg_download': round(avg_download, 2),
        'recent_avg_upload': round(avg_upload, 2),
        'recent_avg_ping': round(avg_ping, 2),
        'total_tests_count': len(test_history)
    }
    
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)