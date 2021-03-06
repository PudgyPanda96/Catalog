from flask import Flask, render_template, request, redirect, jsonify, url_for
from flask import make_response, flash
from flask import session as login_session

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from oauth2client.client import flow_from_clientsecrets, FlowExchangeError
from database_setup import Base, User, Category, Item

import httplib2
import json
import requests
import random
import string
app = Flask(__name__)
app.secret_key = 'super_secret_key'

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']

engine = create_engine('sqlite:///catalog.db',
                       connect_args={'check_same_thread': False}, echo=True)

Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data
    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id
    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    print data['email']
    if session.query(User).filter_by(email=data['email']).count() != 0:
        current_user = session.query(User).filter_by(email=data['email']).one()
    else:
        newUser = User(name=data['name'],
                       email=data['email'])
        session.add(newUser)
        session.commit()
        current_user = newUser

    login_session['user_id'] = current_user.id
    print current_user.id
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '  # noqa
    flash("you are now logged in as %s" % login_session['username'])
    return output


@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps(
        	'Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = "https://accounts.google.com/o/oauth2/revoke?token=%s" % login_session['access_token']  # noqa
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps(
                                'Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


@app.route('/')
@app.route('/category/')
def showCategory():
    """Show all of the categories currently created"""
    categories = session.query(Category).all()
    return render_template('category.html', categories=categories)


@app.route('/category/new/', methods=['GET', 'POST'])
def newCategory():
    """Create a new category"""
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newCategory = Category(name=request.form['name'],
                               user_id=login_session['user_id'])
        session.add(newCategory)
        session.commit
        return redirect(url_for('showCategory'))
    else:
        return render_template('newCategory.html')


@app.route('/category/<int:category_id>/edit/', methods=['GET', 'POST'])
def editCategory(category_id):
    """Edit a category if a user created it"""
    if 'username' not in login_session:
        return redirect('/login')
    editedCategory = session.query(
                                  Category).filter_by(id=category_id).one()
    if request.method == 'POST':
        if request.form['name']:
            editedCategory.name = request.form['name']
            return redirect(url_for('showCategory'))
    else:
        return render_template(
                               'editCategory.html', category=editedCategory)


@app.route('/category/<int:category_id>/delete/', methods=['GET', 'POST'])
def deleteCategory(category_id):
    """Delete the category if the user created it"""
    if 'username' not in login_session:
        return redirect('/login')
    categoryToDelete = session.query(
                                    Category).filter_by(id=category_id).one()

    if category.user_id != login_session['user_id']:
        flash('Category was created by another user and can only be deleted by that user')  # noqa
        return redirect(url_for('showCategory'))

    if request.method == 'POST':
        session.delete(categoryToDelete)
        session.commit()
        return redirect(
                        url_for('showCategory', category_id=category_id))
    else:
        return render_template(
                              'deleteCategory.html', category=categoryToDelete)


@app.route('/category/<int:category_id>/')
@app.route('/category/<int:category_id>/item/')
def showItem(category_id):
    """Show all of the items in a category"""
    category = session.query(Category).filter_by(id=category_id).one()
    items = session.query(Item).filter_by(
                                         category_id=category_id).all()
    return render_template('item.html', items=items, category=category)


@app.route('/category/<int:category_id>/item/new', methods=['GET', 'POST'])
def newItem(category_id):
    """Create a new item for that category"""
    if 'username' not in login_session:
        return redirect('/login')

    category = session.query(Category).filter_by(id=category_id).one()

    if category.user_id != login_session['user_id']:
        flash('Category was created by another user and can only be edited by that user')  # noqa
        return redirect(url_for('showCategory'))

    if request.method == 'POST':
        newItem = Item(name=request.form['name'],
                       description=request.form['description'],
                       category_id=category.id,
                       user_id=category.user_id)
        session.add(newItem)
        session.commit()
        return redirect(url_for('showCategory', category_id=category_id))
    else:
        return render_template('newItem.html', category_id=category_id)

    return render_template('newItem.html', category=category)


@app.route('/category/<int:category_id>/item/<int:item_id>/edit',
           methods=['GET', 'POST'])
def editItem(category_id, item_id):
    """Edit an item if the user created it"""
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(Item).filter_by(id=item_id).one()

    if editedItem.user_id != login_session['user_id']:
        flash('Item was created by another user and can only be edited by that user')  # noqa
        return redirect(url_for('showItem', category_id=category_id))

    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        session.add(editedItem)
        session.commit()
        return redirect(url_for('showCategory', category_id=category_id))
    else:
        return render_template(
                               'editItem.html',
                               category_id=category_id,
                               item_id=item_id,
                               item=editedItem)


@app.route('/category/<int:category_id>/item/<int:item_id>/delete',
           methods=['GET', 'POST'])
def deleteItem(category_id, item_id):
    """Delete an item if teh user created it"""
    if 'username' not in login_session:
        return redirect('/login')

    itemToDelete = session.query(Item).filter_by(id=item_id).one()

    if itemToDelete.user_id != login_session['user_id']:
        flash('Item was created by another user and can only be deleted by that user')  # noqa
        return redirect(url_for('showItem', category_id=category_id))

    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        return redirect(url_for('showCategory', category_id=category_id))
    else:
        return render_template('deleteItem.html', item=itemToDelete)


@app.route('/category/JSON')
def categoriesJSON():
    """Return JSON for all the categories"""
    categorys = session.query(Category).all()
    return jsonify(categories=[c.serialize for c in categorys])


@app.route('/category/<int:category_id>/JSON')
def categoryJSON(category_id):
    """Return JSON of all the items for a category"""
    category = session.query(Category).filter_by(id=category_id).one()
    items = session.query(Item).filter_by(
        category_id=category_id).all()
    return jsonify(items=[i.serialize for i in items])


@app.route('/item/JSON')
def itemsJSON():
    """Return JSON for an item"""
    items = session.query(Item).all()
    return jsonify(items=[i.serialize for i in items])


@app.route('/category/<int:category_id>/item/<int:item_id>/JSON')
def itemJSON(category_id, item_id):
    """Return JSON for an item"""
    item = session.query(Item).filter_by(id=item_id).one()
    return jsonify(item=item.serialize)


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None

if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
