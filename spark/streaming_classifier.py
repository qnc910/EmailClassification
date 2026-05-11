from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, coalesce, lit, udf, lower, when
from pyspark.sql.types import StructType, StructField, StringType, BooleanType
from pyspark.ml import PipelineModel
import imaplib
import email
from email.header import decode_header
import time
import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db_conn():
    return psycopg2.connect(
        host="postgres",
        database="emaildb",
        user="postgres",
        password="123456"
    )

def fetch_emails_from_imap():
    emails_data = []
    try:
        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT email FROM users")
        users = cur.fetchall()

        for user in users:
            email_addr = user['email']
            print(f"Scanning mailbox: {email_addr}")
            try:
                mail = imaplib.IMAP4("greenmail", 3143)
                mail.login(email_addr, "pass")
                mail.select("INBOX")

                status, messages = mail.search(None, 'UNSEEN')
                if status != 'OK':
                    continue

                for num in messages[0].split():
                    status, data = mail.fetch(num, '(RFC822)')
                    if status != 'OK':
                        continue
                    
                    raw_email = data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subject = decode_header(msg.get("Subject", ""))[0][0]
                    if isinstance(subject, bytes):
                        subject = subject.decode()
                    
                    sender = msg.get("From", "")
                    recipient = email_addr
                    
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode()
                                except:
                                    body = str(part.get_payload(decode=True))
                                break
                    else:
                        body = msg.get_payload(decode=True).decode()

                    # --- Deduplication Check ---
                    cur.execute(
                        "SELECT id FROM emails WHERE sender = %s AND recipient = %s AND subject = %s AND body = %s LIMIT 1",
                        (sender, recipient, subject, body)
                    )
                    if cur.fetchone():
                        print(f"Skipping duplicate email: {subject}")
                        mail.store(num, '+FLAGS', '\\Seen')
                        continue

                    emails_data.append({
                        "sender": sender,
                        "recipient": recipient,
                        "subject": subject,
                        "body": body
                    })
                    
                    mail.store(num, '+FLAGS', '\\Seen')

                mail.logout()
            except Exception as e:
                print(f"Error scanning {email_addr}: {e}")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")
    
    return emails_data

def classify():
    # ... (same spark initialization)
    spark = SparkSession.builder \
        .appName("EmailSpamClassification_IMAP") \
        .master("local[*]") \
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.2") \
        .getOrCreate()

    model_path = "/opt/bitnami/spark/models/spam_classification_model"
    model = PipelineModel.load(model_path)

    while True:
        try:
            emails_data = fetch_emails_from_imap()
            if emails_data:
                # We need to explicitly define the schema to avoid empty RDD inference issues
                from pyspark.sql.types import StructType, StructField, StringType
                schema = StructType([
                    StructField("sender", StringType(), True),
                    StructField("recipient", StringType(), True),
                    StructField("subject", StringType(), True),
                    StructField("body", StringType(), True)
                ])
                df = spark.createDataFrame(emails_data, schema=schema)
                df = df.withColumn("text", concat_ws(" ", coalesce(col("subject"), lit("")), coalesce(col("body"), lit(""))))
                
                prediction_df = model.transform(df)
                
                result_df = prediction_df.withColumn(
                    "subject_lower", lower(col("subject"))
                ).withColumn(
                    "body_lower", lower(col("body"))
                ).withColumn(
                    "sender_lower", lower(col("sender"))
                ).withColumn(
                    "category",
                    when(col("sender_lower").like("%facebook.com%") | col("sender_lower").like("%twitter.com%") | col("sender_lower").like("%linkedin.com%"), lit("social"))
                    .when(col("subject_lower").like("%quảng cáo%") | col("subject_lower").like("%khuyến mãi%") | col("subject_lower").like("%sale%") | col("subject_lower").like("%giảm giá%"), lit("ads"))
                    .when(col("prediction") == 1.0, lit("spam"))
                    .otherwise(lit("inbox"))
                ).select(
                    col("sender"),
                    col("recipient"),
                    col("subject"),
                    col("body"),
                    col("category")
                )
                
                result_df.write \
                    .format("jdbc") \
                    .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
                    .option("dbtable", "emails") \
                    .option("user", "postgres") \
                    .option("password", "123456") \
                    .option("driver", "org.postgresql.Driver") \
                    .mode("append") \
                    .save()
                    
                print(f"Processed and classified {len(emails_data)} emails.")
            time.sleep(2)
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(2)

if __name__ == "__main__":
    classify()
