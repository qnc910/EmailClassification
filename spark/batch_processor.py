from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, lit
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
from pyspark.ml import PipelineModel
import os

def process_uploads():
    # 1. Initialize Spark
    spark = SparkSession.builder \
        .appName("EmailClassification_BatchUploads") \
        .master("local[*]") \
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.2") \
        .getOrCreate()

    # 2. Load pre-trained model
    model_path = "/opt/bitnami/spark/models/spam_classification_model"
    if not os.path.exists(model_path):
        print(f"Error: Model not found at {model_path}. Please run train_model.py first.")
        return
    
    model = PipelineModel.load(model_path)

    # 3. Define schema for incoming CSV
    # We support multiple formats but expect at least subject and message/body
    schema = StructType([
        StructField("subject", StringType(), True),
        StructField("message", StringType(), True),
        StructField("isSpam", DoubleType(), True)
    ])

    # 4. Read Stream from the uploads directory
    # Spark will automatically process new files added to this folder
    input_df = spark.readStream \
        .option("header", "true") \
        .schema(schema) \
        .csv("/opt/bitnami/spark/uploads")

    # Pre-process: Rename 'message' to 'body' and ensure 'sender'/'recipient' exist
    # If the CSV doesn't have sender/recipient, we use placeholders
    processed_df = input_df \
        .withColumnRenamed("message", "body") \
        .withColumn("sender", lit("batch_upload@system")) \
        .withColumn("recipient", lit("admin@example.com")) \
        .withColumn("text", concat_ws(" ", col("subject"), col("body")))

    # 5. Predict
    prediction_df = model.transform(processed_df)

    # Convert prediction to BOOLEAN
    result_df = prediction_df.select(
        col("sender"),
        col("recipient"),
        col("subject"),
        col("body"),
        (col("prediction") == 1.0).alias("is_spam")
    )

    # 6. Write results to Postgres
    def write_to_postgres(df, epoch_id):
        df.write \
            .format("jdbc") \
            .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
            .option("dbtable", "emails") \
            .option("user", "postgres") \
            .option("password", "123456") \
            .option("driver", "org.postgresql.Driver") \
            .mode("append") \
            .save()

    query = result_df.writeStream \
        .foreachBatch(write_to_postgres) \
        .option("checkpointLocation", "/tmp/spark_checkpoint_uploads") \
        .start()

    print("Spark is monitoring /opt/bitnami/spark/uploads for new CSV files...")
    query.awaitTermination()

if __name__ == "__main__":
    process_uploads()
