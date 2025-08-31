import time
from config.mysql import get_mysql_connection
from models.app_version import AppVersion
import os

av = AppVersion()
def main():
    try:
        conn1 = get_mysql_connection()
        start_time = time.time()
        versions = av.list_versions()
        end_time = time.time()
        
        print(f"Fetched {len(versions)} app versions in {end_time - start_time:.2f} seconds.")

        print("conn1.open", conn1.open)
        conn1.close()
        print("conn1.open after close", conn1.open)
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
