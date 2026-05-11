from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, lit, coalesce, input_file_name, regexp_extract, regexp_replace, when, lower
from pyspark.sql.types import StructType, StructField, StringType
from pyspark.ml import PipelineModel
import os
import sys

# Import training function from train_model.py
sys.path.append('/opt/bitnami/spark/scripts')
try:
    from train_model import train_from_db
except ImportError:
    print("Warning: Could not import train_from_db. Auto-retraining might not work.")
    train_from_db = None

def process_uploads():
    spark = SparkSession.builder \
        .appName("EmailClassification_BatchUploads") \
        .master("local[*]") \
        .config("spark.driver.memory", "800m") \
        .config("spark.executor.memory", "800m") \
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
            ).withColumn(
                "category",
                when(col("sender_lower").like("%facebook.com%") | col("sender_lower").like("%twitter.com%") | col("sender_lower").like("%linkedin.com%"), lit("social"))
                .when(col("subject_lower").like("%quảng cáo%") | col("subject_lower").like("%khuyến mãi%") | col("subject_lower").like("%sale%") | col("subject_lower").like("%giảm giá%"), lit("ads"))
                .when(col("prediction") == 1.0, lit("spam"))
                .otherwise(lit("inbox"))
            ).select(
                col("sender"),
                col("recipient"),
                col("final_subject").alias("subject"),
                col("final_body").alias("body"),
                col("category")
            )

            # Write results to Postgres
            print(f"Writing {count} predictions to database...")
            result_df.write \
                .format("jdbc") \
                .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
                .option("dbtable", "emails") \
                .option("user", "postgres") \
                .option("password", "123456") \
                .option("driver", "org.postgresql.Driver") \
                .mode("append") \
                .save()
            
            print(f"Batch {epoch_id} written to DB.")

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
