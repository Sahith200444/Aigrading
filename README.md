# AI Descriptive Exam Paper Correction

This project is an AI-powered exam paper correction tool designed to automate the evaluation of descriptive answer scripts. It leverages PDF text extraction, AWS Textract, and Google Generative AI to assess student responses and compute scores according to predefined marking schemes.

## Features

- **Automated Text Extraction:**  
  Convert PDFs to images and extract text using AWS Textract.

- **AI-Powered Evaluation:**  
  Utilize Google Generative AI to evaluate answers based on two distinct question patterns:
  - **Pattern 1:** 10 separate Part-A questions (1 mark each) and 5 Part-B questions (with two subquestions each).
  - **Pattern 2:** 1 Part-A question with 10 subquestions (1 mark each) and 6 Part-B questions.

- **Database Integration:**  
  Store exam submissions and results in a MySQL database.

- **Flask Web Interface:**  
  Upload question papers and answer scripts, view results, and submit final scores via an easy-to-use web dashboard.

## Prerequisites

- **Python 3.8+**
- **MySQL Server:** Ensure you have access to a MySQL database.
- **AWS Account:** Required for AWS Textract with appropriate credentials.
- **Google Generative AI API Key:** For generating and evaluating responses.
- **Other Python Dependencies:** Listed in the `requirements.txt` file.


## Contributing

Contributions, suggestions, or bug reports are welcome! Please feel free to open an issue or submit a pull request for improvements.

Project Link:https://aigrading-kt0g.onrender.com/
Create your login and select IT(III-Year) C-section,the answer scripts in the backend are uploaded in that class Only.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [Flask](https://flask.palletsprojects.com/)
- [AWS Textract](https://aws.amazon.com/textract/)
- [Google Generative AI](https://cloud.google.com/generative-ai)
- [pdf2image](https://github.com/Belval/pdf2image)
- [Pillow (PIL)](https://python-pillow.org/)
- [Flask-MySQLdb](https://flask-mysqldb.readthedocs.io/)

---

