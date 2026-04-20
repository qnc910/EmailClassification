from pyspark.sql import SparkSession
from pyspark.ml.feature import Tokenizer, StopWordsRemover, HashingTF, IDF
from pyspark.ml.classification import NaiveBayes
from pyspark.ml import Pipeline
from pyspark.sql.functions import col, concat_ws

def train():
    spark = SparkSession.builder \
        .appName("EmailSpamClassification_Training") \
        .getOrCreate()

    # 1. Load Data
    # Use data/enron_spam_data.csv (relative to project root)
    data_path = "/opt/bitnami/spark/data/enron_spam_data.csv"
    df = spark.read.csv(data_path, header=True, inferSchema=True)

    # Convert isSpam to double as required by Spark ML
    df = df.withColumn("label", col("isSpam").cast("double"))
    
    # Combined subject and message for text analysis, ensuring string type
    df = df.withColumn("text", concat_ws(" ", col("subject").cast("string"), col("message").cast("string")))
    
    # Drop rows with null values
    df = df.dropna(subset=["text", "label"])

    # 2. Pipeline Stages
    tokenizer = Tokenizer(inputCol="text", outputCol="words")
    remover = StopWordsRemover(inputCol="words", outputCol="filtered_words")
    hashingTF = HashingTF(inputCol="filtered_words", outputCol="raw_features", numFeatures=10000)
    idf = IDF(inputCol="raw_features", outputCol="features")
    nb = NaiveBayes(labelCol="label", featuresCol="features")

    pipeline = Pipeline(stages=[tokenizer, remover, hashingTF, idf, nb])

    # 3. Train Model
    print("Training model...")
    model = pipeline.fit(df)

    # 4. Save Model
    model_path = "/opt/bitnami/spark/models/spam_classification_model"
    model.write().overwrite().save(model_path)
    print(f"Model saved to {model_path}")

    spark.stop()

if __name__ == "__main__":
    train()
