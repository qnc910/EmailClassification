from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, lit, coalesce, input_file_name, regexp_extract, regexp_replace, when, lower
from pyspark.sql.types import StructType, StructField, StringType
from pyspark.ml import PipelineModel
import os
import sys
from urllib.parse import urlparse

# Import training function from train_model.py
sys.path.append('/opt/bitnami/spark/scripts')
try:
    from train_model import train_from_db
except ImportError:
    print("Warning: Could not import train_from_db. Auto-retraining might not work.")
    train_from_db = None

import psycopg2

def execute_db_sql(sql):
    try:
        conn = psycopg2.connect(
            host="postgres",
            database="emaildb",
            user="postgres",
            password="123456"
        )
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB SQL Execution Error: {e}")

def process_uploads():
    spark = SparkSession.builder \
        .appName("EmailClassification_BatchUploads") \
        .master("local[*]") \
        .config("spark.driver.memory", "1500m") \
        .config("spark.executor.memory", "1500m") \
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.2") \
        .getOrCreate()

    spark.sparkContext.setLogLevel("WARN")

    # 2. Define a broad schema to capture various CSV formats
    schema = StructType([
        StructField("subject", StringType(), True),
        StructField("message", StringType(), True),
        StructField("body", StringType(), True),
        StructField("text", StringType(), True),
        StructField("isSpam", StringType(), True),
        StructField("label", StringType(), True),
        StructField("file", StringType(), True)
    ])

    model_path = "/opt/bitnami/spark/models/spam_classification_model"

    # 3. Read Stream from the uploads directory
    print("Spark is starting to monitor /opt/bitnami/spark/uploads...")
    input_df = spark.readStream \
        .option("header", "true") \
        .option("quote", "\"") \
        .option("escape", "\"") \
        .option("multiLine", "true") \
        .schema(schema) \
        .option("maxFilesPerTrigger", 1) \
        .csv("/opt/bitnami/spark/uploads")

    # Pre-process: Prepare unified columns before transformation
    unified_df = input_df \
        .withColumn("file_name", input_file_name()) \
        .withColumn("extracted_email", regexp_replace(regexp_extract(col("file_name"), r"([^/]+)___", 1), "_at_", "@")) \
        .withColumn("recipient", when(col("extracted_email") != "", col("extracted_email")).otherwise(lit("admin@example.com"))) \
        .withColumn("final_body", 
            concat_ws("", 
                coalesce(col("message"), lit("")), 
                coalesce(col("body"), lit("")), 
                coalesce(col("text"), lit(""))
            )
        ) \
        .withColumn("final_subject", 
            coalesce(col("subject"), lit("Batch Upload"))
        ) \
        .withColumn("sender", lit("batch_upload@system")) \
        .withColumn("text_combined", concat_ws(" ", col("final_subject"), col("final_body")))

    # 4. Define writing function with transformation and retraining
    def handle_batch(df, epoch_id):
        count = df.count()
        if count == 0:
            return

        print(f"--- Batch {epoch_id} Start: {count} rows ---")

        # Collect distinct file names to delete later
        file_paths = []
        try:
            rows = df.select("file_name").distinct().collect()
            file_paths = [r["file_name"] for r in rows if r["file_name"]]
        except Exception as ex:
            print(f"Error collecting file names: {ex}")
        
        # Reload latest model for every batch
        if not os.path.exists(model_path):
            print(f"Skipping prediction: Model not found at {model_path}")
            return
            
        try:
            print("Loading latest AI model...")
            current_model = PipelineModel.load(model_path)
            
            # Predict
            # Drop the original 'text' from schema to avoid ambiguity, then rename text_combined to 'text'
            predict_input = df.drop("text").withColumnRenamed("text_combined", "text")
            prediction_df = current_model.transform(predict_input)

            # Map to final schema and determine category
            result_df = prediction_df.withColumn(
                "subject_lower", lower(col("final_subject"))
            ).withColumn(
                "body_lower", lower(col("final_body"))
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
                col("final_subject").alias("subject"),
                col("final_body").alias("body"),
                col("category"),
                col("subcategory")
            )

            # Write results to Postgres
            print(f"Writing {count} predictions to database...")
            try:
                print("Disabling stats trigger for fast batch insert...")
                execute_db_sql("ALTER TABLE emails DISABLE TRIGGER trg_emails_stats;")
            except Exception as trg_err:
                print(f"Warning: Could not disable stats trigger: {trg_err}")

            result_df.write \
                .format("jdbc") \
                .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
                .option("dbtable", "emails") \
                .option("user", "postgres") \
                .option("password", "123456") \
                .option("driver", "org.postgresql.Driver") \
                .option("batchsize", "10000") \
                .mode("append") \
                .save()
            
            try:
                print("Re-enabling stats trigger...")
                execute_db_sql("ALTER TABLE emails ENABLE TRIGGER trg_emails_stats;")
                
                print("Synchronizing email stats...")
                sync_stats_sql = """
                INSERT INTO email_stats (recipient, category, subcategory, count)
                SELECT recipient, category, COALESCE(subcategory, ''), COUNT(*)
                FROM emails
                GROUP BY recipient, category, COALESCE(subcategory, '')
                ON CONFLICT (recipient, category, subcategory)
                DO UPDATE SET count = EXCLUDED.count;
                """
                execute_db_sql(sync_stats_sql)
                print("Stats synchronization complete.")
            except Exception as trg_err:
                print(f"Warning: Could not re-enable trigger or sync stats: {trg_err}")
            
            print(f"Batch {epoch_id} written to DB.")

            # Delete processed files to save space
            for fp in file_paths:
                try:
                    parsed = urlparse(fp)
                    local_path = parsed.path
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        print(f"Deleted processed file: {local_path}")
                except Exception as del_err:
                    print(f"Error deleting file {fp}: {del_err}")

            # Trigger Retraining if batch is large enough (> 500 rows)
            if train_from_db and count >= 500:
                print("Triggering Auto-Retraining...")
                train_from_db()
                print("Auto-Retraining complete.")

        except Exception as e:
            print(f"Error in batch processing: {e}")

    # 5. Start the stream
    query = unified_df.writeStream \
        .foreachBatch(handle_batch) \
        .option("checkpointLocation", "/tmp/spark_checkpoint_uploads") \
        .start()

    query.awaitTermination()

if __name__ == "__main__":
    process_uploads()
