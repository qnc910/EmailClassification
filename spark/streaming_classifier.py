from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, udf
from pyspark.sql.types import StructType, StructField, StringType, IntegerType
from pyspark.ml import PipelineModel

def classify():
    # 1. Initialize Spark
    spark = SparkSession.builder \
        .appName("EmailSpamClassification_Streaming") \
        .master("local[*]") \
        .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,org.postgresql:postgresql:42.7.2") \
        .getOrCreate()

    # 2. Load pre-trained model
    model_path = "/opt/bitnami/spark/models/spam_classification_model"
    model = PipelineModel.load(model_path)

    # 3. Read from Kafka
    kafka_df = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", "kafka:29092") \
        .option("subscribe", "emails") \
        .option("startingOffsets", "earliest") \
        .load()

    # Define schema for the incoming JSON email
    schema = StructType([
        StructField("sender", StringType(), True),
        StructField("recipient", StringType(), True),
        StructField("subject", StringType(), True),
        StructField("body", StringType(), True)
    ])

    # Parse JSON from Kafka value
    # We use coalesce to handle nulls and ensure string type for tokenizer
    from pyspark.sql.functions import concat_ws, coalesce, lit

    email_df = kafka_df.selectExpr("CAST(value AS STRING)") \
        .select(from_json(col("value"), schema).alias("data")) \
        .select("data.*")

    # Combine subject and body for classification using concat_ws (safer and ensures string type)
    email_df = email_df.withColumn(
        "text", 
        concat_ws(" ", coalesce(col("subject"), lit("")), coalesce(col("body"), lit("")))
    )

    # 4. Predict
    prediction_df = model.transform(email_df)

    # Convert prediction (double) to BOOLEAN isSpam
    result_df = prediction_df.select(
        col("sender"),
        col("recipient"),
        col("subject"),
        col("body"),
        (col("prediction") == 1.0).alias("is_spam")
    )

    # 5. Write to Postgres
    def write_to_postgres(df, epoch_id):
        try:
            if df.count() > 0:
                print(f"Batch {epoch_id}: Writing {df.count()} emails to Postgres...")
                df.write \
                    .format("jdbc") \
                    .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
                    .option("dbtable", "emails") \
                    .option("user", "postgres") \
                    .option("password", "123456") \
                    .option("driver", "org.postgresql.Driver") \
                    .mode("append") \
                    .save()
                print(f"Batch {epoch_id}: Write complete.")
        except Exception as e:
            print(f"ERROR Batch {epoch_id}: Failed to write to Postgres: {e}")

    query = result_df.writeStream \
        .foreachBatch(write_to_postgres) \
        .option("checkpointLocation", "/tmp/spark_checkpoint_streaming") \
        .start()

    query.awaitTermination()

if __name__ == "__main__":
    classify()
