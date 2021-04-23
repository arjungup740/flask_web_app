from flask import Flask, render_template

app = Flask(__name__)


@app.route('/trip_roster')
def index():

    return render_template('index.html')

@app.route('/trip_destinations')
def destinations():

    return render_template('trip_destinations.html')
