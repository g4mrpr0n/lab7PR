import json
import time
import pika
from bs4 import BeautifulSoup
import requests
from tinydb import TinyDB
import re
import threading

db = TinyDB('database.json')
counter = threading.Lock()
db_lock = threading.Lock()
url_count = 0
processed_count = 0

consumers = []
def extract_product_details(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')

        details = {}
        for li in soup.find_all('li', class_='m-value'):
            name_span = li.find('span', class_='adPage__content__features__key')
            value_span = li.find('span', class_='adPage__content__features__value')
            if name_span and value_span:
                name = name_span.text.strip()
                value = value_span.text.strip()
                details[name] = value

        return details
    except Exception as e:
        print(f"Error in extract_product_details: {e}")
        return None


def callback(ch, method, properties, body):
    print(f"\nConsuming URL: {body.decode()}")
    global url_count, processed_count
    url = body.decode()
    result_json = extract_product_details(url)
    print(result_json)

    if isinstance(result_json, str):
        result_dict = json.loads(result_json)
    else:
        result_dict = result_json

    with db_lock:
        db.insert(result_dict)

    with counter:
        processed_count += 1

    if processed_count >= url_count:
        print("Stopping consumer as all URLs have been processed.")
        ch.stop_consuming()

    ch.basic_ack(delivery_tag=method.delivery_tag)

def consume_urls(i):
    print(f"Starting consumer {i}...")
    time.sleep(i)
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    while True:
        method_frame = channel.queue_declare(queue='url_queue', passive=True)
        message_count = method_frame.method.message_count

        if message_count == 0:
            print(f"All URLs have been processed. Stopping consumer {i}.")
            break

        try:
            # set auto_ack to False
            channel.basic_consume(queue='url_queue', on_message_callback=callback, auto_ack=False)
            print(f"Consumer {i} is processing a URL.")
            channel.start_consuming()
        except pika.exceptions.ChannelClosedByBroker:
            pass
        except Exception as e:
            print(f"Error in consume_urls: {e}")


def scrape_page(url):
    global url_count
    print(f"Scraping page: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    base_url = 'https://999.md'

    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    channel.queue_declare(queue='url_queue')

    limit = 20
    added_urls = set()
    for link in soup.find_all('a'):
        url = link.get('href')
        if url and re.match(r'/ro/\d+', url) and 'booster' not in url:
            absolute_url = base_url + url

            if absolute_url not in added_urls:
                added_urls.add(absolute_url)

                print(f"Publishing URL: {absolute_url}")
                channel.basic_publish(exchange='', routing_key='url_queue', body=absolute_url)

                with counter:
                    url_count += 1

                if url_count >= limit:
                    break


if __name__ == "__main__":
    scrape_page("https://999.md/ro/list/phone-and-communication/mobile-phones")

    for i in range(5):  
        consumer_thread = threading.Thread(target=consume_urls, args=(i,))
        consumers.append(consumer_thread)
        consumer_thread.start()

    for consumer in consumers:
        consumer.join()