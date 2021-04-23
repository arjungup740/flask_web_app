from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def front_page():

    return render_template('template.html')

@app.route('/trip_roster')
def trip_roster():

    return render_template('trip_roster.html')

@app.route('/trip_destinations')
def trip_destinations():

    return render_template('trip_destinations.html')
