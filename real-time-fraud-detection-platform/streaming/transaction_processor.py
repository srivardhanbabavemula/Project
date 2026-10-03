"""
Spark Structured Streaming Job for Real-Time Transaction Processing

Consumes transactions from Kafka, computes real-time features, and writes to feature store.
"""

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, from_json, window, count, sum as spark_sum, avg, max as spark_max,
    min as spark_min, stddev, current_timestamp, unix_timestamp, lit,
    when, datediff, hour, dayofweek, lag, expr
)
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, 
    BooleanType, TimestampType
)
from pyspark.sql.window import Window
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Define schema for incoming Kafka messages
TRANSACTION_SCHEMA = StructType([
    StructField("transaction_id", StringType(), False),
    StructField("user_id", StringType(), False),
    StructField("amount", DoubleType(), False),
    StructField("currency", StringType(), False),
    StructField("merchant_id", StringType(), False),
    StructField("merchant_category", StringType(), False),
    StructField("country", StringType(), False),
    StructField("device_id", StringType(), False),
    StructField("ip_address", StringType(), False),
    StructField("card_last_4", StringType(), False),
    StructField("cvv_match", BooleanType(), False),
    StructField("billing_zip_match", BooleanType(), False),
    StructField("timestamp", TimestampType(), False),
    StructField("is_fraud", BooleanType(), False),
    StructField("processing_status", StringType(), False),
])


class TransactionProcessor:
    """Real-time transaction processing with Spark Structured Streaming"""
    
    def __init__(self, 
                 kafka_servers: str = None,
                 kafka_topic: str = None,
                 checkpoint_location: str = None,
                 postgres_url: str = None,
                 postgres_user: str = None,
                 postgres_password: str = None):
        
        db_host = os.environ.get("DB_HOST", "localhost")
        db_port = os.environ.get("DB_PORT", "5433")
        db_name = os.environ.get("DB_NAME", "fraud_detection")
        
        kafka_servers = kafka_servers or os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
        kafka_topic = kafka_topic or os.environ.get("KAFKA_TOPIC", "payment-transactions")
        checkpoint_location = checkpoint_location or os.environ.get("SPARK_CHECKPOINT_DIR", "/tmp/spark-checkpoints")
        postgres_url = postgres_url or os.environ.get("DB_JDBC_URL", f"jdbc:postgresql://{db_host}:{db_port}/{db_name}")
        postgres_user = postgres_user or os.environ.get("DB_USER", "frauduser")
        postgres_password = postgres_password or os.environ.get("DB_PASSWORD", "fraudpass123")
        
        self.kafka_servers = kafka_servers
        self.kafka_topic = kafka_topic
        self.checkpoint_location = checkpoint_location
        self.postgres_url = postgres_url
        self.postgres_user = postgres_user
        self.postgres_password = postgres_password
        
        # Initialize Spark Session
        self.spark = self._create_spark_session()
        
    def _create_spark_session(self) -> SparkSession:
        """Create Spark session with required configurations"""
        
        spark = (SparkSession.builder
                .appName("FraudDetectionStreaming")
                .config("spark.jars.packages", 
                       "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,"
                       "org.postgresql:postgresql:42.7.1")
                .config("spark.sql.streaming.checkpointLocation", self.checkpoint_location)
                .config("spark.sql.shuffle.partitions", "4")
                .config("spark.streaming.kafka.consumer.cache.enabled", "false")
                .getOrCreate())
        
        spark.sparkContext.setLogLevel("WARN")
        logger.info("Spark session created successfully")
        
        return spark
    
    def read_kafka_stream(self):
        """Read streaming data from Kafka"""
        
        df = (self.spark
              .readStream
              .format("kafka")
              .option("kafka.bootstrap.servers", self.kafka_servers)
              .option("subscribe", self.kafka_topic)
              .option("startingOffsets", "latest")
              .option("maxOffsetsPerTrigger", 1000)
              .load())
        
        # Parse JSON from Kafka value
        transactions = (df
                       .selectExpr("CAST(value AS STRING) as json_value")
                       .select(from_json(col("json_value"), TRANSACTION_SCHEMA).alias("data"))
                       .select("data.*"))
        
        logger.info(f"Reading from Kafka topic: {self.kafka_topic}")
        return transactions
    
    def compute_velocity_features(self, transactions):
        """
        Compute velocity features using windowed aggregations
        
        Features:
        - Transactions in last 1 hour, 24 hours, 7 days
        - Total spend in last 1 hour, 24 hours, 7 days
        - Average transaction amount
        - Transaction amount std dev
        """
        
        # Add watermark for late data (allow 10 minutes late)
        transactions_with_watermark = transactions.withWatermark("timestamp", "10 minutes")
        
        # User-level velocity features
        user_velocity = (transactions_with_watermark
                        .groupBy(
                            col("user_id"),
                            window(col("timestamp"), "1 hour")
                        )
                        .agg(
                            count("*").alias("txn_count_1h"),
                            spark_sum("amount").alias("total_amount_1h"),
                            avg("amount").alias("avg_amount_1h"),
                            stddev("amount").alias("stddev_amount_1h"),
                            spark_max("amount").alias("max_amount_1h")
                        )
                        .select(
                            col("user_id"),
                            col("window.end").alias("window_end"),
                            col("txn_count_1h"),
                            col("total_amount_1h"),
                            col("avg_amount_1h"),
                            col("stddev_amount_1h"),
                            col("max_amount_1h")
                        ))
        
        return user_velocity
    
    def compute_behavioral_features(self, transactions):
        """
        Compute behavioral features
        
        Features:
        - New device flag
        - New country flag
        - Transaction hour (risk profile)
        - Day of week pattern
        """
        
        # Add derived time features
        behavioral = (transactions
                     .withColumn("hour_of_day", hour(col("timestamp")))
                     .withColumn("day_of_week", dayofweek(col("timestamp")))
                     .withColumn("is_weekend", 
                                when((col("day_of_week") == 1) | (col("day_of_week") == 7), True)
                                .otherwise(False))
                     .withColumn("is_night_txn", 
                                when((col("hour_of_day") >= 0) & (col("hour_of_day") <= 6), True)
                                .otherwise(False))
                     .withColumn("cvv_match_int", col("cvv_match").cast("int"))
                     .withColumn("billing_zip_match_int", col("billing_zip_match").cast("int")))
        
        return behavioral
    
    def compute_merchant_features(self, transactions):
        """
        Compute merchant-level features
        
        Features:
        - Merchant fraud rate (historical)
        - Average merchant transaction amount
        - Merchant transaction count
        """
        
        merchant_stats = (transactions
                         .groupBy(
                             col("merchant_id"),
                             window(col("timestamp"), "24 hours")
                         )
                         .agg(
                             count("*").alias("merchant_txn_count_24h"),
                             avg("amount").alias("merchant_avg_amount_24h"),
                             spark_sum(col("is_fraud").cast("int")).alias("merchant_fraud_count_24h")
                         )
                         .select(
                             col("merchant_id"),
                             col("window.end").alias("window_end"),
                             col("merchant_txn_count_24h"),
                             col("merchant_avg_amount_24h"),
                             (col("merchant_fraud_count_24h") / col("merchant_txn_count_24h"))
                                .alias("merchant_fraud_rate_24h")
                         ))
        
        return merchant_stats
    
    def write_to_postgres(self, df, table_name: str, mode: str = "append"):
        """Write streaming dataframe to PostgreSQL"""
        
        query = (df.writeStream
                .foreachBatch(lambda batch_df, batch_id: 
                             self._write_batch_to_postgres(batch_df, table_name, mode))
                .outputMode("update")
                .option("checkpointLocation", f"{self.checkpoint_location}/{table_name}")
                .start())
        
        return query
    
    def _write_batch_to_postgres(self, batch_df, table_name: str, mode: str):
        """Write a micro-batch to PostgreSQL"""
        
        if batch_df.count() > 0:
            (batch_df.write
             .format("jdbc")
             .option("url", self.postgres_url)
             .option("dbtable", table_name)
             .option("user", self.postgres_user)
             .option("password", self.postgres_password)
             .option("driver", "org.postgresql.Driver")
             .mode(mode)
             .save())
            
            logger.info(f"Written {batch_df.count()} rows to {table_name}")
    
    def write_to_console(self, df, query_name: str):
        """Write streaming output to console for debugging"""
        
        query = (df.writeStream
                .outputMode("update")
                .format("console")
                .option("truncate", False)
                .queryName(query_name)
                .start())
        
        return query
    
    def run(self):
        """Run the streaming pipeline"""
        
        logger.info("Starting Spark Structured Streaming job...")
        
        # Read from Kafka
        transactions = self.read_kafka_stream()
        
        # Compute features
        behavioral_features = self.compute_behavioral_features(transactions)
        velocity_features = self.compute_velocity_features(transactions)
        merchant_features = self.compute_merchant_features(transactions)
        
        # Write raw transactions to database
        raw_query = self.write_to_postgres(behavioral_features, "transactions")
        
        # Write velocity features
        velocity_query = self.write_to_postgres(velocity_features, "user_velocity_features")
        
        # Write merchant features
        merchant_query = self.write_to_postgres(merchant_features, "merchant_features")
        
        # Debug: Write to console
        console_query = self.write_to_console(
            behavioral_features.select("transaction_id", "user_id", "amount", "is_fraud"),
            "transaction_debug"
        )
        
        logger.info("All streaming queries started successfully")
        
        # Wait for termination
        self.spark.streams.awaitAnyTermination()


def main():
    """Entry point for the streaming job"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Spark Structured Streaming for Fraud Detection")
    parser.add_argument("--kafka-servers", default="localhost:19092", help="Kafka bootstrap servers")
    parser.add_argument("--kafka-topic", default="payment-transactions", help="Kafka topic")
    parser.add_argument("--checkpoint-dir", default="/tmp/spark-checkpoints", help="Checkpoint directory")
    
    args = parser.parse_args()
    
    processor = TransactionProcessor(
        kafka_servers=args.kafka_servers,
        kafka_topic=args.kafka_topic,
        checkpoint_location=args.checkpoint_dir
    )
    
    processor.run()


if __name__ == "__main__":
    main()
