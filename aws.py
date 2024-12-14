from flask import Flask, render_template, request, redirect, url_for, flash
from flask_mysqldb import MySQL
import google.generativeai as genai
from datetime import datetime
from pdf2image import convert_from_path
from PIL import Image
import os
import boto3
import io
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Secret key for session management
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'abc3445')

# MySQL configuration
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'root')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'papers')

# Initialize MySQL
mysql = MySQL(app)

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Set up Google Generative AI SDK
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

def gpt(questions, answers):
    try:
        user_input = "You are an examiner. Just give only the score for the above questions each question is out of 5m and give marks individually for each question and the ouput should be only score. Question paper: " + questions + " Answerscript: " + answers
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(user_input)
        scores = [int(s.strip()) for s in response.text.split() if s.strip().isdigit()][:6]  # Limit to 6 scores
        return scores
    except Exception as e:
        return f"An error occurred: {e}"

@app.route('/')
@app.route('/dash.html', methods=['GET', 'POST'])
def dash():
    if request.method == 'POST':
        stu_name = request.form['studentName']
        stu_roll = request.form['rollNo']
        q_paper = request.files['questionPaper']
        a_paper = request.files['answerScript']

        if q_paper and a_paper:
            q_paper_filename = os.path.join(UPLOAD_FOLDER, q_paper.filename)
            a_paper_filename = os.path.join(UPLOAD_FOLDER, a_paper.filename)
            q_paper.save(q_paper_filename)
            a_paper.save(a_paper_filename)

            cursor = mysql.connection.cursor()
            cursor.execute("INSERT INTO paper (stu_name, stu_roll, questionpaper, answerscript, created_at) VALUES (%s, %s, %s, %s, %s)",
                           (stu_name, stu_roll, q_paper.filename, a_paper.filename, datetime.now()))
            mysql.connection.commit()
            cursor.close()

            flash('File successfully uploaded')
            return redirect(url_for('result'))

    return render_template('dash.html')

@app.route('/result', methods=['GET', 'POST'])
def result():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT questionpaper, answerscript, stu_roll FROM paper ORDER BY created_at DESC LIMIT 1")
    result = cursor.fetchone()
    cursor.close()

    if result:
        questionpaper_filename = result[0]
        answerscript_filename = result[1]
        stu_roll = result[2]

        questionpaper_path = os.path.join(UPLOAD_FOLDER, questionpaper_filename)
        answerscript_path = os.path.join(UPLOAD_FOLDER, answerscript_filename)

        questions = extract_text_from_pdf(questionpaper_path)
        answers = extract_text_from_pdf(answerscript_path)

        scores = gpt(questions, answers)
        if isinstance(scores, str):  # Check if there was an error
            flash(scores)
            return redirect(url_for('dash'))
    else:
        flash('No files found for processing')
        return redirect(url_for('dash'))

    return render_template('result.html', questions=questions, answers=answers, scores=scores, answerscript_filename=answerscript_filename)

@app.route('/submit_scores', methods=['POST'])
def submit_scores():
    scores = request.form.getlist('scores')
    # Process the submitted scores as needed
    flash('Scores successfully submitted')
    return redirect(url_for('dash'))

def extract_text_from_pdf(pdf_path):
    images = convert_from_path(pdf_path)
    text = ''
    for image in images:
        text += extract_text_from_image(image)
    return text

def extract_text_from_image(image):
    client = boto3.client(
        'textract',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name='us-east-1'
    )

    image_byte_array = io.BytesIO()
    image.save(image_byte_array, format='PNG')
    content = image_byte_array.getvalue()

    response = client.detect_document_text(Document={'Bytes': content})
    blocks = response['Blocks']
    texts = [block['Text'] for block in blocks if block['BlockType'] == 'LINE']

    return "\n".join(texts)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=True)
