#! /usr/bin/env python3.6

"""
app.py
Stripe Payments Demo. Created by Adrienne Dreyfus (@adrind).

This is our Flask server that handles requests from our Stripe checkout flow.
It has all the endpoints you need to accept payments.

Python 3.6 or newer required.
"""

import stripe
import json
import setup
import os
import sift

from inventory import Inventory
from stripe_types import Source
from flask import Flask, render_template, jsonify, request, send_from_directory
from dotenv import load_dotenv, find_dotenv

static_dir = f'{os.path.abspath(os.path.join(__file__ ,"../../.."))}/public'
app = Flask(__name__, static_folder=static_dir)


@app.route('/')
def home():
    return send_from_directory(static_dir, 'index.html')


# Serve static assets and images for index.html
# Note: You can remove this if your frontend code is using Flask's templating
@app.route('/javascripts/<path:path>', methods=['GET'])
def serve_js(path):
    return send_from_directory(f'{static_dir}/javascripts', path)


@app.route('/stylesheets/<path:path>', methods=['GET'])
def serve_css(path):
    return send_from_directory(f'{static_dir}/stylesheets', path)


@app.route('/images/<path:path>', methods=['GET'])
def serve_image(path):
    return send_from_directory(f'{static_dir}/images', path)


# Serve config set up in .env
@app.route('/config')
def get_config():
    return jsonify({
        'stripePublishableKey': os.getenv('STRIPE_PUBLISHABLE_KEY'),
        'stripeCountry': os.getenv('STRIPE_ACCOUNT_COUNTRY') or 'US',
        'country': 'US',
        'currency': 'eur',
        'paymentMethods': os.getenv('PAYMENT_METHODS').split(', ') if os.getenv('PAYMENT_METHODS') else ['card'],
        'shippingOptions': [
        {
            'id': 'free',
            'label': 'Free Shipping',
            'detail': 'Delivery within 5 days',
            'amount': 0,
        },
        {
            'id': 'express',
            'label': 'Express Shipping',
            'detail': 'Next day delivery',
            'amount': 500,
        }
        ]
    })


@app.route('/products', methods=['GET'])
def get_products():
    products = Inventory.list_products()
    if Inventory.products_exist(products):
        return jsonify(products)
    else:
        # Create Products for our Stripe store if we haven't already.
        setup.create_data()
        products = Inventory.list_products()
        return jsonify(products)


@app.route('/products/<string:product_id>', methods=['GET'])
def retrieve_product(product_id):
    return jsonify(Inventory.retrieve_product(product_id))


@app.route('/payment_intents', methods=['POST'])
def make_payment_intent():
    # Creates a new PaymentIntent with items from the cart.
    data = json.loads(request.data)
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=Inventory.calculate_payment_amount(items=data['items']),
            currency=data['currency'],
            payment_method_types=os.getenv(
                'PAYMENT_METHODS').split(', ') if os.getenv(
                'PAYMENT_METHODS') else ['card']
        )

        return jsonify({'paymentIntent': payment_intent})
    except Exception as e:
        return jsonify(e), 403


@app.route('/payment_intents/<string:id>/shipping_change', methods=['POST'])
def update_payment_intent(id):
    data = json.loads(request.data)
    amount = Inventory.calculate_payment_amount(items=data['items'])
    amount += Inventory.get_shipping_cost(data['shippingOption']['id'])
    try:
        payment_intent = stripe.PaymentIntent.modify(
            id,
            amount=amount
        )

        return jsonify({'paymentIntent': payment_intent})
    except Exception as e:
        return jsonify(e), 403


@app.route('/webhook', methods=['POST'])
def webhook_received():
    # You can use webhooks to receive information about asynchronous payment events.
    # For more about our webhook events check out https://stripe.com/docs/webhooks.
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    request_data = json.loads(request.data)

    if webhook_secret:
        # Retrieve the event by verifying the signature using the raw body and secret if webhook signing is configured.
        signature = request.headers.get('stripe-signature')
        try:
            event = stripe.Webhook.construct_event(
                payload=request.data, sig_header=signature, secret=webhook_secret)
            data = event['data']
        except Exception as e:
            return e
        # Get the type of webhook event sent - used to check the status of PaymentIntents.
        event_type = event['type']
    else:
        data = request_data['data']
        event_type = request_data['type']
    data_object = data['object']

    # PaymentIntent Beta, see https://stripe.com/docs/payments/payment-intents
    # Monitor payment_intent.succeeded & payment_intent.payment_failed events.
    if data_object['object'] == 'payment_intent':
        payment_intent = data_object

        if event_type == 'payment_intent.succeeded':
            print('🔔  Webhook received! Payment for PaymentIntent ' +
                  payment_intent['id']+' succeeded')
        elif event_type == 'payment_intent.payment_failed':
            print('🔔  Webhook received! Payment on source ' + payment_intent['last_payment_error']['source']['id'] +
                  ' for PaymentIntent ' + payment_intent['id'] + ' failed.')

    # Monitor `source.chargeable` events.
    if data_object['object'] == 'source' \
            and data_object['status'] == 'chargeable' \
            and 'paymentIntent' in data_object['metadata']:
        source = data_object
        print(f'🔔  Webhook received! The source {source["id"]} is chargeable')

        # Find the corresponding PaymentIntent this Source is for by looking in its metadata.
        payment_intent = stripe.PaymentIntent.retrieve(
            source['metadata']['paymentIntent'])

        # Verify that this PaymentIntent actually needs to be paid.
        if payment_intent['status'] != 'requires_payment_method':
            return jsonify({'error': f'PaymentIntent already has a status of {payment_intent["status"]}'}), 403

        # INTEGRATION POINT to make sift request
        client = sift.Client(api_key='11105a0ef0ae6b81', account_id='5c8affc84f0c93d33c7c4d6d')

        # Sample $create_order event
        properties = {
          # Required Fields
          "$user_id"          : "billy_jones_301",
          # Supported Fields
          "$session_id"       : "gigtleqddo84l8cm15qe4il",
          "$order_id"         : "ORDER-28168441",
          "$user_email"       : "bill@gmail.com",
          "$amount"           : 115940000, # $115.94
          "$currency_code"    : "USD",
          "$billing_address"  : {
              "$name"         : "Bill Jones",
              "$phone"        : "1-415-555-6041",
              "$address_1"    : "2100 Main Street",
              "$address_2"    : "Apt 3B",
              "$city"         : "New London",
              "$region"       : "New Hampshire",
              "$country"      : "US",
              "$zipcode"      : "03257"
          },
          "$payment_methods"  : [
              {
                  "$payment_type"    : "$credit_card",
                  "$payment_gateway" : "$braintree",
                  "$card_bin"        : "542486",
                  "$card_last4"      : "4444"
              }
          ],
          "$shipping_address"  : {
              "$name"          : "Bill Jones",
              "$phone"         : "1-415-555-6041",
              "$address_1"     : "2100 Main Street",
              "$address_2"     : "Apt 3B",
              "$city"          : "New London",
              "$region"        : "New Hampshire",
              "$country"       : "US",
              "$zipcode"       : "03257"
          },
          "$expedited_shipping" : True,
          "$shipping_method"    : "$physical",
          "$items"             : [
            {
              "$item_id"        : "12344321",
              "$product_title"  : "Microwavable Kettle Corn: Original Flavor",
              "$price"          : 4990000, # $4.99
              "$upc"            : "097564307560",
              "$sku"            : "03586005",
              "$brand"          : "Peters Kettle Corn",
              "$manufacturer"   : "Peters Kettle Corn",
              "$category"       : "Food and Grocery",
              "$tags"           : ["Popcorn", "Snacks", "On Sale"],
              "$quantity"       : 4
            },
            {
              "$item_id"        : "B004834GQO",
              "$product_title"  : "The Slanket Blanket-Texas Tea",
              "$price"          : 39990000, # $39.99
              "$upc"            : "6786211451001",
              "$sku"            : "004834GQ",
              "$brand"          : "Slanket",
              "$manufacturer"   : "Slanket",
              "$category"       : "Blankets & Throws",
              "$tags"           : ["Awesome", "Wintertime specials"],
              "$color"          : "Texas Tea",
              "$quantity"       : 2
            }
          ],
          # For marketplaces, use $seller_user_id to identify the seller
          "$seller_user_id"     : "slinkys_emporium",

          "$promotions"         : [
            {
              "$promotion_id" : "FirstTimeBuyer",
              "$status"       : "$success",
              "$description"  : "$5 off",
              "$discount"     : {
                "$amount"                   : 5000000,  # $5.00
                "$currency_code"            : "USD",
                "$minimum_purchase_amount"  : 25000000  # $25.00
              }
            }
          ],

          # Sample Custom Fields
          "digital_wallet"      : "apple_pay", # "google_wallet", etc.
          "coupon_code"         : "dollarMadness",
          "shipping_choice"     : "FedEx Ground Courier",
          "is_first_time_buyer" : False,

          # Send this information from a BROWSER client.
          "$browser"      : {
            "$user_agent" :  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36"
          },

          # =========================================

          # Send this information from an APP client.
          "$app"        : {
            # Example for the iOS Calculator app.
            "$os"                  : "iOS",
            "$os_version"          : "10.1.3",
            "$device_manufacturer" : "Apple",
            "$device_model"        : "iPhone 4,2",
            "$device_unique_id"    : "A3D261E4-DE0A-470B-9E4A-720F3D3D22E6",
            "$app_name"            : "Calculator",
            "$app_version"         : "3.2.7"
          }
        }

        response = client.track("$create_order", properties)

        # https://stripe.com/docs/api/payment_intents/confirm?disable_syntax_highlighting=1&expand_all_subspecs=1
        payment_intent.confirm(source=source['id'])

        # payment_request_valid = False
        # payment_request_valid = response.is_ok() && response.api_status == 0
        #
        # if payment_request_valid: 
        #     print('payment request passed fraud check')
        #     # Confirm the PaymentIntent with the chargeable source.
        #     payment_intent.confirm(source=source['id'])
        # else:
        #     print('fraud detected')

    # Monitor `source.failed` and `source.canceled` events.
    if data_object['object'] == 'source' and data_object['status'] in ['failed', 'canceled']:
        # Cancel the PaymentIntent.
        source = data_object
        intent = stripe.PaymentIntent.retrieve(
            source['metadata']['paymentIntent'])
        intent.cancel()

    return jsonify({'status': 'success'})


@app.route('/payment_intents/<string:id>/status', methods=['GET'])
def retrieve_payment_intent_status(id):
    payment_intent = stripe.PaymentIntent.retrieve(id)
    return jsonify({'paymentIntent': {'status': payment_intent["status"]}})


if __name__ == '__main__':
    load_dotenv(find_dotenv())
    stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
    stripe.api_version = '2019-02-11'
    app.run()
