from flask import Flask, render_template

app = Flask(__name__)


@app.route('/trip_roster')
def index():

    return render_template('index.html')

@app.route('/destinations')
def destinations():

    print_string =\
    """
    Locations:<br> 
<p style="margin-left: 20px">US Virgin Islands</p>
<p style="margin-left: 20px">Puerto Rico</p>
<p style="margin-left: 20px">Tahoe</p>
<p style="margin-left: 20px">San Diego</p>
    """
    return print_string
