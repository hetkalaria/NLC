import boto3
import requests
import json
import time
import logging
import base64
import uuid
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def create_error_response(status_code, error_message, error_details=None):
    body = {
        'error': str(error_message),
        'details': error_details if error_details else str(error_message)
    }
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }

def lambda_handler(event, context):
    try:
        # Log the incoming event
        logger.info(f"Incoming event: {json.dumps(event)}")
        
        # 1. Parse the request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError as e:
            return create_error_response(400, "Invalid JSON in request body")

        # 2. Extract and validate parameters
        bucket_name = 'awshugb'
        pdf_base64 = body.get('pdf_base64')
        question = body.get('question')

        if not all([pdf_base64, question]):
            missing_params = []
            if not pdf_base64: missing_params.append('pdf_base64')
            if not question: missing_params.append('question')
            return create_error_response(400, f"Missing required parameters: {', '.join(missing_params)}")

        # 3. Generate a unique key for the PDF file
        pdf_key = f"uploads/{uuid.uuid4()}.pdf"

        # 4. Upload PDF to S3
        s3_client = boto3.client('s3')
        try:
            pdf_data = base64.b64decode(pdf_base64)
            s3_client.put_object(Bucket=bucket_name, Key=pdf_key, Body=pdf_data)
            logger.info("Successfully uploaded PDF to S3")
        except ClientError as e:
            return create_error_response(500, f"S3 upload error: {str(e)}")

        # 5. Start Textract processing
        try:
            textract_client = boto3.client('textract')
            start_response = textract_client.start_document_text_detection(
                DocumentLocation={'S3Object': {'Bucket': bucket_name, 'Name': pdf_key}}
            )
            job_id = start_response['JobId']
            logger.info(f"Started Textract job: {job_id}")

            # 6. Wait for Textract job completion
            text = ""
            max_retries = 12  # 1 minute total (5 seconds * 12)
            for attempt in range(max_retries):
                job_status = textract_client.get_document_text_detection(JobId=job_id)
                status = job_status['JobStatus']
                logger.info(f"Textract job status: {status} (attempt {attempt + 1})")

                if status == "SUCCEEDED":
                    # Extract text with pagination handling
                    pages_text = []
                    next_token = None
                    
                    while True:
                        if next_token:
                            response = textract_client.get_document_text_detection(
                                JobId=job_id,
                                NextToken=next_token
                            )
                        else:
                            response = job_status

                        for block in response.get('Blocks', []):
                            if block.get('BlockType') == 'LINE':
                                pages_text.append(block.get('Text', ''))

                        next_token = response.get('NextToken')
                        if not next_token:
                            break

                    text = " ".join(pages_text)
                    logger.info(f"Extracted text length: {len(text)}")
                    break

                elif status == "FAILED":
                    return create_error_response(500, "Textract processing failed", 
                                              job_status.get('StatusMessage', 'No error details available'))

                time.sleep(5)

            if not text:
                return create_error_response(500, "Textract processing timeout")

            # 7. Generate answer using Hugging Face API
            try:
                api_url = "Model_URL"
                headers = {
                    "Authorization": "Bearer xx_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "Content-Type": "application/json"
                }

                # Split text into smaller chunks if needed
                max_context_length = 2000
                text_chunk = text[:max_context_length]
                # text_chunk = text

                # Format the prompt as a single string
                prompt = f"Provide a detailed answer to the following question based on the context. Only respond with the answer, without any additional questions.\n\nContext: {text_chunk}\n\nQuestion: {question}\n\nAnswer:"
                
                api_response = requests.post(
                    api_url,
                    headers=headers,
                    json={
                        "inputs": prompt,
                        "parameters": {
                            "max_length": 500,
                            "temperature": 0.7
                        }
                    },
                    timeout=30
                )
                
                logger.info(f"HF API Status: {api_response.status_code}")
                logger.info(f"HF API Response: {api_response.text}")

                if api_response.status_code != 200:
                    return create_error_response(500, f"Hugging Face API error: {api_response.text}")

                # Parse the response
                response_data = api_response.json()
                if isinstance(response_data, list):
                    answer = response_data[0].get('generated_text', 'No answer found')
                else:
                    answer = response_data.get('generated_text', 'No answer found')

                # Clean up the answer by removing the prompt
                answer = answer.replace(prompt, '').strip()

                # Delete the uploaded PDF from S3 after processing
                try:
                    s3_client.delete_object(Bucket=bucket_name, Key=pdf_key)
                    logger.info(f"Deleted PDF from S3: {pdf_key}")
                except ClientError as e:
                    logger.error(f"Error deleting PDF from S3: {str(e)}")

                # 8. Return successful response
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'question': question,
                        'answer': answer,
                        'textPreview': text[:200] + "..." if len(text) > 200 else text
                    })
                }

            except requests.exceptions.RequestException as e:
                return create_error_response(500, f"Error calling Hugging Face API: {str(e)}")

        except Exception as e:
            return create_error_response(500, f"Textract processing error: {str(e)}")

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return create_error_response(500, f"Unexpected error: {str(e)}")