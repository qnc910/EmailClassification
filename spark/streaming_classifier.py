from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, coalesce, lit, udf, lower, when, regexp_extract
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
        cur.execute("SELECT email FROM users WHERE last_active_at IS NOT NULL AND last_active_at >= NOW() - INTERVAL '30 seconds'")
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
                
                # Dynamic subclassification and categorization
                result_df = prediction_df.withColumn(
                    "subject_lower", lower(col("subject"))
                ).withColumn(
                    "body_lower", lower(col("body"))
                ).withColumn(
                    "sender_lower", lower(col("sender"))
                )

                domain_expr = regexp_extract(col("sender_lower"), r"@([a-z0-9.-]+)", 1)
                raw_brand_expr = regexp_extract(domain_expr, r"(?:^|\.)([a-z0-9-]+)\.[a-z]+(?:\.[a-z]+)?$", 1)
                
                brand_cleaned = (
                    when(raw_brand_expr == "facebookmail", lit("facebook"))
                    .when(raw_brand_expr == "linkedinmail", lit("linkedin"))
                    .otherwise(raw_brand_expr)
                )
                
                is_generic = brand_cleaned.isin("gmail", "yahoo", "outlook", "hotmail", "live", "icloud", "mail", "protonmail", "zoho", "yandex", "system")
                
                is_social_domain = brand_cleaned.isin("facebook", "instagram", "twitter", "linkedin", "tiktok", "pinterest", "youtube", "reddit", "threads", "mastodon", "tumblr", "discord", "snapchat", "telegram", "zalo")
                is_ad_domain = brand_cleaned.isin("shopee", "lazada", "tiki", "grab", "momo", "netflix", "spotify", "amazon", "ebay", "sendo", "traveloka", "agoda")
                
                is_social_keyword = (
                    col("subject_lower").like("%facebook%") | col("sender_lower").like("%facebook%") |
                    col("subject_lower").like("%instagram%") | col("sender_lower").like("%instagram%") |
                    col("subject_lower").like("%twitter%") | col("sender_lower").like("%twitter%") |
                    col("subject_lower").like("%linkedin%") | col("sender_lower").like("%linkedin%") |
                    col("subject_lower").like("%tiktok%") | col("sender_lower").like("%tiktok%") |
                    col("subject_lower").like("%pinterest%") | col("sender_lower").like("%pinterest%") |
                    col("subject_lower").like("%youtube%") | col("sender_lower").like("%youtube%") |
                    col("subject_lower").like("%reddit%") | col("sender_lower").like("%reddit%") |
                    col("subject_lower").like("%threads%") | col("sender_lower").like("%threads%")
                )

                is_ad_keyword = (
                    col("subject_lower").like("%shopee%") | col("sender_lower").like("%shopee%") |
                    col("subject_lower").like("%lazada%") | col("sender_lower").like("%lazada%") |
                    col("subject_lower").like("%tiki%") | col("sender_lower").like("%tiki%") |
                    col("subject_lower").like("%grab%") | col("sender_lower").like("%grab%") |
                    col("subject_lower").like("%momo%") | col("sender_lower").like("%momo%") |
                    col("subject_lower").like("%netflix%") | col("sender_lower").like("%netflix%") |
                    col("subject_lower").like("%spotify%") | col("sender_lower").like("%spotify%") |
                    col("subject_lower").like("%amazon%") | col("sender_lower").like("%amazon%") |
                    col("subject_lower").like("%ebay%") | col("sender_lower").like("%ebay%") |
                    col("subject_lower").like("%sendo%") | col("sender_lower").like("%sendo%")
                )

                is_promo_text = (
                    col("subject_lower").like("%quảng cáo%") | col("subject_lower").like("%khuyến mãi%") |
                    col("subject_lower").like("%quang cao%") | col("subject_lower").like("%khuyen mai%") |
                    col("subject_lower").like("%sale%") | col("subject_lower").like("%giảm giá%") |
                    col("subject_lower").like("%giam gia%") |
                    col("subject_lower").like("%voucher%") | col("subject_lower").like("%ưu đãi%") |
                    col("subject_lower").like("%uu dai%") | col("subject_lower").like("%khuyến mại%") |
                    col("subject_lower").like("%coupon%") | col("subject_lower").like("%discount%") |
                    col("subject_lower").like("%promo%")
                )

                text_brand = (
                    when(col("subject_lower").like("%facebook%") | col("sender_lower").like("%facebook%"), lit("facebook"))
                    .when(col("subject_lower").like("%instagram%") | col("sender_lower").like("%instagram%"), lit("instagram"))
                    .when(col("subject_lower").like("%twitter%") | col("sender_lower").like("%twitter%"), lit("twitter"))
                    .when(col("subject_lower").like("%linkedin%") | col("sender_lower").like("%linkedin%"), lit("linkedin"))
                    .when(col("subject_lower").like("%tiktok%") | col("sender_lower").like("%tiktok%"), lit("tiktok"))
                    .when(col("subject_lower").like("%pinterest%") | col("sender_lower").like("%pinterest%"), lit("pinterest"))
                    .when(col("subject_lower").like("%youtube%") | col("sender_lower").like("%youtube%"), lit("youtube"))
                    .when(col("subject_lower").like("%reddit%") | col("sender_lower").like("%reddit%"), lit("reddit"))
                    .when(col("subject_lower").like("%threads%") | col("sender_lower").like("%threads%"), lit("threads"))
                    .when(col("subject_lower").like("%shopee%") | col("sender_lower").like("%shopee%"), lit("shopee"))
                    .when(col("subject_lower").like("%lazada%") | col("sender_lower").like("%lazada%"), lit("lazada"))
                    .when(col("subject_lower").like("%tiki%") | col("sender_lower").like("%tiki%"), lit("tiki"))
                    .when(col("subject_lower").like("%grab%") | col("sender_lower").like("%grab%"), lit("grab"))
                    .when(col("subject_lower").like("%momo%") | col("sender_lower").like("%momo%"), lit("momo"))
                    .when(col("subject_lower").like("%netflix%") | col("sender_lower").like("%netflix%"), lit("netflix"))
                    .when(col("subject_lower").like("%spotify%") | col("sender_lower").like("%spotify%"), lit("spotify"))
                    .when(col("subject_lower").like("%amazon%") | col("sender_lower").like("%amazon%"), lit("amazon"))
                    .when(col("subject_lower").like("%ebay%") | col("sender_lower").like("%ebay%"), lit("ebay"))
                    .when(col("subject_lower").like("%sendo%") | col("sender_lower").like("%sendo%"), lit("sendo"))
                    .otherwise(lit(None).cast(StringType()))
                )

                is_social_general_keyword = (
                    col("subject_lower").like("%mạng xã hội%") | col("subject_lower").like("%mang xa hoi%") |
                    col("subject_lower").like("%lời mời kết bạn%") | col("subject_lower").like("%loi moi ket ban%") |
                    col("subject_lower").like("%friend request%") | col("subject_lower").like("%commented on%") |
                    col("subject_lower").like("%mentioned you%") | col("subject_lower").like("%liked your%") |
                    col("subject_lower").like("%báo cáo hàng tuần%") | col("subject_lower").like("%thông báo mới từ%")
                )

                is_ad_general_keyword = (
                    col("subject_lower").like("%quà tặng%") | col("subject_lower").like("%qua tang%") |
                    col("subject_lower").like("%deal sốc%") | col("subject_lower").like("%deal soc%") |
                    col("subject_lower").like("%mua ngay%") | col("subject_lower").like("%promotion%") |
                    col("subject_lower").like("%advertising%") | col("subject_lower").rlike(r"\boff\b")
                )

                is_social = (
                    is_social_domain | 
                    (is_social_keyword & is_generic) | 
                    (is_social_general_keyword & is_generic)
                )

                is_ads = (
                    is_ad_domain | 
                    is_promo_text | 
                    (is_ad_keyword & is_generic) | 
                    (is_ad_general_keyword & is_generic)
                )

                category_col = (
                    when(col("prediction") == 1.0, lit("spam"))
                    .when(is_social, lit("social"))
                    .when(is_ads, lit("ads"))
                    .otherwise(lit("inbox"))
                )

                subcategory_col = (
                    when(category_col == "social",
                        when(text_brand.isNotNull(), text_brand)
                        .when(~is_generic & (brand_cleaned != ""), brand_cleaned)
                        .otherwise(lit("other"))
                    )
                    .when(category_col == "ads",
                        when(text_brand.isNotNull(), text_brand)
                        .when(~is_generic & (brand_cleaned != ""), brand_cleaned)
                        .otherwise(lit("other"))
                    )
                    .otherwise(lit(None).cast(StringType()))
                )

                result_df = result_df.withColumn(
                    "category", category_col
                ).withColumn(
                    "subcategory", subcategory_col
                ).select(
                    col("sender"),
                    col("recipient"),
                    col("subject"),
                    col("body"),
                    col("category"),
                    col("subcategory")
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
