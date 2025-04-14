import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
import google.generativeai as genai
from datetime import datetime
from pdf2image import convert_from_bytes
from PIL import Image
import boto3
import io
from dotenv import load_dotenv
import re

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'abc3445')

# MySQL configuration
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'mysql-28dcd4ff-msahithreddy5-4da4.k.aivencloud.com')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'avnadmin')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'AVNS_Q_u_BmO5V9Yg15HT3Wn')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'defaultdb')
mysql = MySQL(app)

# Configure google generative AI
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "text/plain",
}
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
)

# Helper: Create an S3 client
def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    )

# Helper: Generate a presigned URL for an S3 object
def get_s3_presigned_url(s3_key):
    s3 = get_s3_client()
    bucket_name = os.getenv('S3_BUCKET')
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket_name, 'Key': s3_key},
        ExpiresIn=3600  # URL valid for 1 hour
    )

# Helper: Download PDF from S3 and extract its text
def extract_text_from_pdf_s3(s3_key):
    s3 = get_s3_client()
    bucket_name = os.getenv('S3_BUCKET')
    response = s3.get_object(Bucket=bucket_name, Key=s3_key)
    pdf_bytes = response['Body'].read()
    images = convert_from_bytes(pdf_bytes)
    text = ''
    for image in images:
        text += extract_text_from_image(image)
    return text

# Helper: Use Textract to extract text from an image
def extract_text_from_image(image):
    client = boto3.client(
        'textract',
        aws_access_key_id=os.getenv('AWS_TEXTRACT_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_TEXTRACT_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )
    image_byte_array = io.BytesIO()
    image.save(image_byte_array, format='PNG')
    content = image_byte_array.getvalue()
    response = client.detect_document_text(Document={'Bytes': content})
    blocks = response.get('Blocks', [])
    texts = [block['Text'] for block in blocks if block.get('BlockType') == 'LINE']
    return "\n".join(texts)

def determine_pattern(questions_text):
    lower_text = questions_text.lower()
    if "question 11" in lower_text or "q11" in lower_text:
        return "pattern1"
    elif "question 1" in lower_text and "a)" in lower_text:
        return "pattern2"
    else:
        return "pattern1"

def gpt(questions, answers, pattern_type="pattern1"):
    try:
        if pattern_type == "pattern1":
            user_input = f"""Evaluate the answer script strictly following these rules:

PART-A (10 questions, 1 mark each):
- Return 10 scores separated by spaces (0.0 or 0.5 or 1.0)
Example: '1.0 0.5 1.0 0.0 1.0 0.5 1.0 1.0 0.5 1.0'

PART-B (5 main questions Q11-Q15, each with subquestions a and b):
- For each answered subquestion, use format 'q<x><y>:score' where <x> is the question number (11-15) and <y> is either a or b.
- Score must be between 0.0 and 10.0

QUESTION PAPER:
{questions}

ANSWER SCRIPT:
{answers}
"""
        elif pattern_type == "pattern2":
            user_input = f"""Evaluate the answer script strictly following these rules:

PART-A (1 question with 10 subquestions a-j, 1 mark each):
- Return 10 scores in the format '1a:score 1b:score ... 1j:score'
Example: '1a:1.0 1b:0.5 1c:1.0 1d:0.0 1e:1.0 1f:0.5 1g:1.0 1h:1.0 1i:0.5 1j:1.0'

PART-B (6 main questions Q2-Q7):
- For each answered question, use format 'q<x>:score'
- Score must be between 0.0 and 10.0

QUESTION PAPER:
{questions}

ANSWER SCRIPT:
{answers}
"""
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(user_input)
        response_text = response.text.strip().lower()

        if pattern_type == "pattern1":
            part_a_pattern = re.compile(r'\b(0\.0|0\.5|1\.0)\b')
            part_a_matches = part_a_pattern.findall(response_text)
            if len(part_a_matches) >= 10:
                part_a_scores = [float(s) for s in part_a_matches[:10]]
            else:
                part_a_scores = [0.0] * 10

            part_b_pattern = re.compile(r'q(\d{2})(a|b):\s*(\d+(?:\.\d+)?)')
            part_b_matches = part_b_pattern.findall(response_text)
            part_b_dict = {}
            for match in part_b_matches:
                q_num = int(match[0])
                sub_q = match[1]
                score = float(match[2])
                if 11 <= q_num <= 15:
                    key = f"{q_num}{sub_q}"
                    if key in part_b_dict:
                        part_b_dict[key] = max(part_b_dict[key], score)
                    else:
                        part_b_dict[key] = score
            part_b_scores = []
            for q in range(11, 16):
                for sub in ['a', 'b']:
                    key = f"{q}{sub}"
                    val = part_b_dict.get(key, 0.0)
                    part_b_scores.append(max(0.0, min(val, 10.0)))
            return part_a_scores + part_b_scores

        elif pattern_type == "pattern2":
            part_a_pattern = re.compile(r'1([a-j]):\s*(\d+(?:\.\d+)?)')
            part_a_matches = part_a_pattern.findall(response_text)
            part_a_scores = [0.0] * 10
            for match in part_a_matches:
                sub = match[0]
                score = float(match[1])
                idx = ord(sub) - ord('a')
                part_a_scores[idx] = max(0.0, min(score, 1.0))
            
            part_b_pattern = re.compile(r'q([2-7]):\s*(\d+(?:\.\d+)?)')
            part_b_matches = part_b_pattern.findall(response_text)
            part_b_dict = {str(q): 0.0 for q in range(2, 8)}
            for match in part_b_matches:
                q = match[0]
                score = float(match[1])
                part_b_dict[q] = max(0.0, min(score, 10.0))
            part_b_scores = [part_b_dict[str(q)] for q in range(2, 8)]
            return part_a_scores + part_b_scores

    except Exception as e:
        return f"Evaluation error: {str(e)}"

# ---------- Authentication Routes ----------

# ---------- Authentication Routes ----------

@app.route('/', methods=['GET'])
def index():
    # Render the combined login/registration page (auth.html)
    return render_template('auth.html')

@app.route('/login', methods=['POST'])
def do_login():
    email = request.form.get('loginEmail')
    password = request.form.get('loginPassword')
    
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM login WHERE email=%s AND password=%s", (email, password))
    user = cursor.fetchone()
    cursor.close()
    
    if user:
        # Set session data (using full_name as username)
        session['username'] = user[0]
        # Check if the credentials are exactly M Sahith Reddy, msahithreddy5@gmail.com
        # (If needed, you could also check for the roll number "12" if that data is available)
        if user[0] == "M Sahith Reddy" and user[1] == "msahithreddy5@gmail.com":
            return redirect(url_for('dash'))
        else:
            return redirect(url_for('yearselection'))
    else:
        flash('Invalid credentials. Please try again.')
        return redirect(url_for('index'))

@app.route('/register', methods=['POST'])
def do_register():
    full_name = request.form.get('fullName')
    email = request.form.get('registerEmail')
    password = request.form.get('registerPassword')
    confirmPassword = request.form.get('confirmPassword')
    
    if password != confirmPassword:
        flash("Passwords do not match.")
        return redirect(url_for('index'))
    
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM login WHERE email=%s", (email,))
    user = cursor.fetchone()
    
    if user:
        flash("User already exists with that email.")
        cursor.close()
        return redirect(url_for('index'))
    
    cursor.execute("INSERT INTO login (full_name, email, password) VALUES (%s, %s, %s)",
                   (full_name, email, password))
    mysql.connection.commit()
    cursor.close()
    
    flash("Registration successful. Please login.")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash("You have been logged out.")
    return redirect(url_for('index'))

# New Year Selection Route
@app.route('/yearselection', methods=['GET', 'POST'])
def yearselection():
    if 'username' not in session:
        flash("Please log in to access this page.")
        return redirect(url_for('index'))
    
    if request.method == "POST":
        year = request.form.get('year')
        branch = request.form.get('branch')
        section = request.form.get('section')
        # Redirect to /result with the selected criteria as query parameters.
        return redirect(url_for('result', year=year, branch=branch, section=section))
    
    return render_template('yearselection.html')



@app.route('/dash.html', methods=['GET', 'POST'])
def dash():
    # Check if the user is logged in via session
    if 'username' not in session:
        flash("Please log in to access the dashboard.")
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        stu_name = request.form['studentName']
        stu_roll = request.form['rollNo']
        year = request.form['year']
        branch = request.form['branch']
        section = request.form['section']
        q_paper = request.files['questionPaper']
        a_paper = request.files['answerScript']

        if q_paper and a_paper:
            s3 = get_s3_client()
            bucket_name = os.getenv('S3_BUCKET')
            # Create S3 keys (you can add a timestamp or unique identifier for production)
            q_paper_key = f"uploads/{q_paper.filename}"
            a_paper_key = f"uploads/{a_paper.filename}"
            # Upload files to S3
            s3.upload_fileobj(q_paper, bucket_name, q_paper_key, ExtraArgs={'ContentType': q_paper.content_type})
            s3.upload_fileobj(a_paper, bucket_name, a_paper_key, ExtraArgs={'ContentType': a_paper.content_type})
            
            # Save the S3 keys in your database
            cursor = mysql.connection.cursor()
            cursor.execute("INSERT INTO paper (stu_name, stu_roll, year, branch, section, questionpaper, answerscript, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                           (stu_name, stu_roll, year, branch, section, q_paper_key, a_paper_key, datetime.now()))
            mysql.connection.commit()
            cursor.close()

            flash('File successfully uploaded')
            return redirect(url_for('dash'))
    return render_template('dash.html')

@app.route('/result', methods=['GET', 'POST'])
def result():
    # Get the selected criteria from the query parameters
    year = request.args.get('year')
    branch = request.args.get('branch')
    section = request.args.get('section')
    selected_roll = request.args.get('roll_no')

    if not (year and branch and section):
        flash("Year, branch, and section are required.")
        return redirect(url_for('dash'))
    
    cursor = mysql.connection.cursor()
    cursor.execute(
        "SELECT questionpaper, answerscript, stu_roll FROM paper WHERE year=%s AND branch=%s AND section=%s ORDER BY created_at DESC",
        (year, branch, section)
    )
    records = cursor.fetchall()
    cursor.close()

    if not records:
        flash('No records found for the selected criteria')
        return redirect(url_for('dash'))

    # Build a list of roll numbers for the sidebar.
    roll_numbers = [record[2] for record in records]

    # Determine which record to display.
    record_to_display = None
    if selected_roll:
        for record in records:
            if record[2] == selected_roll:
                record_to_display = record
                break
    if not record_to_display:
        record_to_display = records[0]

    q_paper_key = record_to_display[0]
    a_paper_key = record_to_display[1]
    stu_roll = record_to_display[2]

    # Extract texts from PDFs.
    questions = extract_text_from_pdf_s3(q_paper_key)
    answers = extract_text_from_pdf_s3(a_paper_key)

    pattern_type = determine_pattern(questions)
    scores = gpt(questions, answers, pattern_type=pattern_type)
    if isinstance(scores, str):
        flash(scores)
        return redirect(url_for('result'))

    # Generate a presigned URL for the answer script.
    answerscript_url = get_s3_presigned_url(a_paper_key)

    return render_template('result.html', 
                           scores=scores, 
                           answerscript_url=answerscript_url,
                           stu_roll=stu_roll,
                           pattern_type=pattern_type,
                           roll_numbers=roll_numbers,
                           year=year,
                           branch=branch,
                           section=section)


@app.route('/submit_scores', methods=['POST'])
def submit_scores():
    try:
        scores = list(map(float, request.form.getlist('scores')))
        roll_no = request.form['roll_no']
        year = request.form.get('year')
        branch = request.form.get('branch')
        section = request.form.get('section')
        total_score = sum(scores)

        cursor = mysql.connection.cursor()
        cursor.execute("INSERT INTO result (Roll_no, score) VALUES (%s, %s)", 
                       (roll_no, total_score))
        mysql.connection.commit()

        # Retrieve all roll numbers for the selected criteria.
        cursor.execute(
            "SELECT stu_roll FROM paper WHERE year=%s AND branch=%s AND section=%s ORDER BY created_at DESC",
            (year, branch, section)
        )
        records = cursor.fetchall()
        cursor.close()

        roll_numbers = [record[0] for record in records]

        # Find the current roll number's index.
        try:
            current_index = roll_numbers.index(roll_no)
        except ValueError:
            current_index = -1

        # If there's a next roll, redirect to its result page.
        if current_index != -1 and current_index + 1 < len(roll_numbers):
            next_roll = roll_numbers[current_index + 1]
            flash('Scores successfully submitted')
            return redirect(url_for('result', year=year, branch=branch, section=section, roll_no=next_roll))
        else:
            flash('All roll numbers have been scored. Redirecting to year selection.')
            return redirect(url_for('yearselection'))
    except Exception as e:
        flash(f'Error submitting scores: {str(e)}')
        return redirect(url_for('dash'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)), debug=True)
