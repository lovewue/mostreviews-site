from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key'

login_manager = LoginManager()
login_manager.init_app(app)

# Dummy user database
users = {'admin': {'password': 'password123'}}

class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            login_user(User(username))
            return redirect(url_for('edit_wue'))
        return "Invalid credentials", 401
    return '''
    <form method="post">
        Username: <input name="username"><br>
        Password: <input name="password" type="password"><br>
        <input type="submit" value="Login">
    </form>
    '''

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/edit-wue', methods=['GET', 'POST'])
@login_required
def edit_wue():
    file_path = 'top-100-sellers/wue.html'
    if request.method == 'POST':
        new_name = request.form['name']
        # Update <span id="name">...</span> in wue.html
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()
        html = re.sub(r'(<span id="name">)(.*?)(</span>)', f'\\1{new_name}\\3', html)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html)
        return redirect(url_for('edit_wue'))

    # Get current value for the form
    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()
    match = re.search(r'<span id="name">(.*?)</span>', html)
    current_name = match.group(1) if match else ''
    return render_template('edit_wue.html', name=current_name)
