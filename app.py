from flask import Flask, flash, render_template, request, redirect, url_for, session
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'group11_secret'

def get_db():
    conn = mysql.connector.connect(
        host="localhost", user="root", password="Rudra@7711", database="CustomerSupportDB"
    )
    return conn, conn.cursor(dictionary=True)

# --- CUSTOMER ACTIONS ---
@app.route('/follow_up/<int:ticket_id>')
def follow_up(ticket_id):
    conn, cursor = get_db()
    # Increases count and ensures ticket is 'Open' so staff sees it
    cursor.execute("""
        UPDATE Tickets 
        SET FollowUpCount = FollowUpCount + 1, Status = 'Open' 
        WHERE Ticket_ID = %s
    """, (ticket_id,))
    conn.commit()
    conn.close()
    flash("Follow-up sent! Support has been notified.", "info")
    return redirect(url_for('home'))

@app.route('/search_history', methods=['POST'])
def search_history():
    email = request.form.get('search_email')
    f_status = request.form.get('filter_status')
    f_prio = request.form.get('filter_priority')
    
    conn, cursor = get_db()
    cursor.execute("SELECT Customer_ID, Name FROM Customers WHERE Email_ID = %s", (email,))
    customer = cursor.fetchone()
    
    history = []
    if customer:
        query = "SELECT * FROM Tickets WHERE Customer_ID = %s"
        params = [customer['Customer_ID']]
        if f_status:
            query += " AND Status = %s"; params.append(f_status)
        if f_prio:
            query += " AND Priority = %s"; params.append(f_prio)
        
        query += " ORDER BY Ticket_ID DESC"
        cursor.execute(query, params)
        history = cursor.fetchall()
    conn.close()

    # Smart Redirect: Stay on Dashboard if user is Staff
    if 'user' in session:
        conn, cursor = get_db()
        cursor.execute("SELECT Agent_ID, Name FROM Support_Agents WHERE Role='Agent'")
        agents = cursor.fetchall()
        conn.close()
        return render_template('dashboard.html', tickets=history, user=session['user'], agents=agents, is_search=True, last_email=email)
    
    return render_template('raise_ticket.html', history=history, customer_name=customer['Name'] if customer else "", last_email=email)

# --- CORE TICKETING ---
@app.route('/')
def home():
    return render_template('raise_ticket.html', history=[], customer_name="")

@app.route('/raise_ticket', methods=['POST'])
def raise_ticket():
    email, subject, desc, prio = request.form.get('email'), request.form.get('subject'), request.form.get('description'), request.form.get('priority')
    conn, cursor = get_db()
    cursor.execute("SELECT Customer_ID FROM Customers WHERE Email_ID = %s", (email,))
    customer = cursor.fetchone()
    if not customer:
        cursor.execute("INSERT INTO Customers (Name, Email_ID) VALUES (%s, %s)", (email.split('@')[0], email))
        customer_id = cursor.lastrowid
    else:
        customer_id = customer['Customer_ID']
    cursor.execute("INSERT INTO Tickets (Customer_ID, Subject, Description, Priority, Status, FollowUpCount) VALUES (%s, %s, %s, %s, 'Open', 0)", 
                   (customer_id, subject, desc, prio))
    conn.commit(); conn.close()
    flash("Ticket raised successfully!", "success")
    return redirect(url_for('home'))

@app.route('/ticket/<int:ticket_id>/conversation', methods=['GET', 'POST'])
def ticket_conversation(ticket_id):
    conn, cursor = get_db()
    cursor.execute("SELECT * FROM Tickets WHERE Ticket_ID = %s", (ticket_id,))
    ticket = cursor.fetchone()

    if request.method == 'POST' and ticket['Status'] == 'Open':
        msg_text = request.form.get('message')
        user = session.get('user')
        role = user['Role'] if user else 'Customer'
        cursor.execute("INSERT INTO Ticket_Conversations (Ticket_ID, Sender_Role, Message_Text) VALUES (%s, %s, %s)",
                       (ticket_id, role, msg_text))
        conn.commit()
        return redirect(url_for('ticket_conversation', ticket_id=ticket_id))

    cursor.execute("SELECT * FROM Ticket_Conversations WHERE Ticket_ID = %s ORDER BY Timestamp ASC", (ticket_id,))
    messages = cursor.fetchall()
    conn.close()
    return render_template('conversation.html', ticket=ticket, messages=messages)

# --- STAFF DASHBOARD & ADMIN ---
@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login_page'))
    user = session['user']
    f_status, f_prio, f_date = request.args.get('status'), request.args.get('priority'), request.args.get('date')

    conn, cursor = get_db()
    query = "SELECT t.*, (SELECT Message_Text FROM Ticket_Conversations WHERE Ticket_ID = t.Ticket_ID ORDER BY Timestamp DESC LIMIT 1) as last_message FROM Tickets t WHERE 1=1"
    params = []
    if user['Role'] != 'Administrator':
        query += " AND (Agent_ID = %s OR Agent_ID IS NULL)"; params.append(user['Agent_ID'])
    if f_status: query += " AND Status = %s"; params.append(f_status)
    if f_prio: query += " AND Priority = %s"; params.append(f_prio)
    if f_date: query += " AND DATE(Timestamp) = %s"; params.append(f_date)

    # CRITICAL: Order by FollowUpCount so urgent tickets appear first
    query += " ORDER BY FollowUpCount DESC, Ticket_ID DESC"
    cursor.execute(query, params)
    tickets = cursor.fetchall()
    cursor.execute("SELECT Agent_ID, Name FROM Support_Agents WHERE Role='Agent'")
    agents = cursor.fetchall()
    conn.close()
    return render_template('dashboard.html', tickets=tickets, user=user, agents=agents, is_search=False)

@app.route('/admin_report')
def admin_report():
    if 'user' not in session or session['user']['Role'] != 'Administrator': return redirect(url_for('dashboard'))
    conn, cursor = get_db()
    cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN Status='Resolved' THEN 1 ELSE 0 END) as resolved, SUM(CASE WHEN Status='Open' THEN 1 ELSE 0 END) as pending FROM Tickets")
    stats = cursor.fetchone()
    cursor.execute("SELECT a.Name, COUNT(t.Ticket_ID) as assigned, SUM(CASE WHEN t.Status = 'Resolved' THEN 1 ELSE 0 END) as solved FROM Support_Agents a LEFT JOIN Tickets t ON a.Agent_ID = t.Agent_ID WHERE a.Role = 'Agent' GROUP BY a.Agent_ID, a.Name")
    performance = cursor.fetchall()
    conn.close()
    return render_template('admin_report.html', stats=stats, performance=performance)

@app.route('/login_page')
def login_page(): return render_template('login.html')

@app.route('/auth', methods=['POST'])
def auth():
    email = request.form['email']
    conn, cursor = get_db()
    cursor.execute("SELECT * FROM Support_Agents WHERE Email_ID = %s", (email,))
    user = cursor.fetchone()
    conn.close()
    if user:
        session['user'] = user
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/assign_ticket/<int:ticket_id>', methods=['POST'])
def assign_ticket(ticket_id):
    if 'user' in session and session['user']['Role'] == 'Administrator':
        agent_id = request.form.get('agent_id')
        conn, cursor = get_db()
        cursor.execute("UPDATE Tickets SET Agent_ID = %s WHERE Ticket_ID = %s", (agent_id if agent_id else None, ticket_id))
        conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/resolve_ticket/<int:ticket_id>')
def resolve_ticket(ticket_id):
    if 'user' in session:
        conn, cursor = get_db()
        cursor.execute("UPDATE Tickets SET Status = 'Resolved' WHERE Ticket_ID = %s", (ticket_id,))
        conn.commit(); conn.close()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)