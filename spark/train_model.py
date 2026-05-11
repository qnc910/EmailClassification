from pyspark.sql import SparkSession
from pyspark.ml.feature import Tokenizer, StopWordsRemover, HashingTF, IDF
from pyspark.ml.classification import NaiveBayes
from pyspark.ml import Pipeline
from pyspark.sql.functions import col, concat_ws, coalesce, lit
import os

def train_from_db():
    spark = SparkSession.builder \
        .appName("EmailSpamClassification_Retraining") \
        .config("spark.driver.memory", "800m") \
        .config("spark.executor.memory", "800m") \
        .config("spark.jars.packages", "org.postgresql:postgresql:42.7.2") \
        .getOrCreate()

    print("Fetching data from PostgreSQL for retraining...")
    
    # 1. Load Data from DB
    try:
        df = spark.read \
            .format("jdbc") \
            .option("url", "jdbc:postgresql://postgres:5432/emaildb") \
            .option("dbtable", "(SELECT * FROM emails ORDER BY id DESC LIMIT 50000) AS recent_emails") \
            .option("user", "postgres") \
            .option("password", "123456") \
            .option("driver", "org.postgresql.Driver") \
            .option("fetchsize", "5000") \
            .load()

        # Check if we have enough data
        count = df.count()
        if count < 10:
            print(f"Not enough data to train (only {count} rows). Skipping.")
            return

        # 2. Pre-process
        # Convert is_spam boolean to double label
        df = df.withColumn("label", col("is_spam").cast("double"))
        
        # Combined subject and message, handling nulls
        df = df.withColumn("text", 
            concat_ws(" ", 
                coalesce(col("subject"), lit("")), 
                coalesce(col("body"), lit(""))
            )
        )
        
        # Drop rows with null text
        df = df.dropna(subset=["text", "label"])

        # 3. Pipeline Stages (same as original)
        tokenizer = Tokenizer(inputCol="text", outputCol="words")
        remover = StopWordsRemover(inputCol="words", outputCol="filtered_words")
        hashingTF = HashingTF(inputCol="filtered_words", outputCol="raw_features", numFeatures=10000)
        idf = IDF(inputCol="raw_features", outputCol="features")
        nb = NaiveBayes(labelCol="label", featuresCol="features")

        pipeline = Pipeline(stages=[tokenizer, remover, hashingTF, idf, nb])

        # 4. Train Model
        print(f"Retraining model on {count} records...")
        model = pipeline.fit(df)

        # 5. Save Model
        model_path = "/opt/bitnami/spark/models/spam_classification_model"
        model.write().overwrite().save(model_path)
        print(f"Model successfully updated and saved to {model_path}")

    except Exception as e:
        print(f"Retraining Error: {e}")

if __name__ == "__main__":
    train_from_db()
