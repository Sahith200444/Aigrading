import os
from flask import Flask, render_template, request, redirect, url_for, flash
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
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'sql12.freesqldatabase.com')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'sql12763236')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'DV3kKNJmYI')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'sql12763236')
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

@app.route('/', methods=['GET'])
def index():
    # Render the combined login/registration page
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
        # Successful login; redirect to dashboard
        return redirect(url_for('dash'))
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

# ---------- Existing Routes ----------

@app.route('/dash.html', methods=['GET', 'POST'])
def dash():
    if request.method == 'POST':
        stu_name = request.form['studentName']
        stu_roll = request.form['rollNo']
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
            cursor.execute("INSERT INTO paper (stu_name, stu_roll, questionpaper, answerscript, created_at) VALUES (%s, %s, %s, %s, %s)",
                           (stu_name, stu_roll, q_paper_key, a_paper_key, datetime.now()))
            mysql.connection.commit()
            cursor.close()

            flash('File successfully uploaded')
            return redirect(url_for('result'))
    return render_template('dash.html')

@app.route('/result', methods=['GET', 'POST'])
def result():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT questionpaper, answerscript, stu_roll FROM paper ORDER BY created_at DESC LIMIT 1")
    result_data = cursor.fetchone()
    cursor.close()

    if result_data:
        q_paper_key = result_data[0]
        a_paper_key = result_data[1]
        stu_roll = result_data[2]

        questions = extract_text_from_pdf_s3(q_paper_key)
        answers = extract_text_from_pdf_s3(a_paper_key)

        pattern_type = determine_pattern(questions)
        scores = gpt(questions, answers, pattern_type=pattern_type)
        if isinstance(scores, str):
            flash(scores)
            return redirect(url_for('dash'))

        # Generate a presigned URL for the answer script PDF for display in the iframe
        answerscript_url = get_s3_presigned_url(a_paper_key)
    else:
        flash('No files found for processing')
        return redirect(url_for('dash'))

    return render_template('result.html', 
                           scores=scores, 
                           answerscript_url=answerscript_url,
                           stu_roll=stu_roll,
                           pattern_type=pattern_type)

@app.route('/submit_scores', methods=['POST'])
def submit_scores():
    try:
        scores = list(map(float, request.form.getlist('scores')))
        roll_no = request.form['roll_no']
        total_score = sum(scores)

        cursor = mysql.connection.cursor()
        cursor.execute("INSERT INTO result (Roll_no, score) VALUES (%s, %s)", 
                       (roll_no, total_score))
        mysql.connection.commit()
        cursor.close()

        flash('Scores successfully submitted')
        return redirect(url_for('dash'))
    except Exception as e:
        flash(f'Error submitting scores: {str(e)}')
        return redirect(url_for('dash'))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)), debug=True)
