<img width="100%" src="./hero.png"/>

# Bullet Train REST API

## Development Environment

```
pip install virtualenv
virtualenv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
python src/manage.py migrate
python src/manage.py runserver
```

The application can also be run locally using Docker Compose if required, however, it's beneficial 
to run locally using the above steps as it gives you hot reloading. To run using docker compose, 
simply run the following command from the project root: 

```
docker-compose up
```

## Initialising
Once the app has been deployed, you can initialise it to create a super user by hitting the 
`/api/auth/init` endpoint. This will create a super user with the details configured in 
`app.settings.common` with the following parameters: 

```
ADMIN_USERNAME,
ADMIN_EMAIL,
ADMIN_INITIAL_PASSWORD
``` 

These can be updated before deployment, or equally, once initialised, you can log in and update 
these details.

## Databases
Databases are configured in app/settings/\<env\>.py

We use sqlite locally as it's easy to get set up and doesn't require any additional dependencies, 
etc. In production, the app is configured to use PostgreSQL when running using a Heroku-ish 
platform. NoSQL database systems will require some more complicated set up as Django is not 
designed for use with NoSQL databases.

When running on a Heroku-ish platform, the application reads the database connection in production 
from an environment variable called `DATABASE_URL`. This should be configured in the Heroku-ish 
application configuration.  

When running using Docker, it reads the database configuration from the settings located at 
`app.settings.master-docker`

## Deploying

### Using Heroku-ish Platform (e.g. Heroku, Dokku, Flynn)
The application should run on any Heroku-ish platform (e.g. Dokku, Flynn) by simply adding the 
required git repo and pushing the code. The code for running the app is contained in the Procfile.

To get it running, you'll need to update the ALLOWED_HOSTS constant in the relevant settings file. 
If you're running the application using a Heroku-ish platform, you'll need to edit this in 
`app.settings.master`. If you're deploying itusing Docker, you'll need to update this value in 
`app.settings.master-docker`.

NOTE: It is important to also set an environment variable on whatever platform you are using for 
`DJANGO_SECRET_KEY`. There is a function to create one in `app.settings.common` if none exists in 
the environment variables, however, this is not suitable for use in production. To generate a new 
secret key, you can use the function defined in `src/secret-key-gen.py` by simply running it from a 
command prompt: 

```
python secret-key-gen.py 
```

### Using Docker
The application can be configured to run using docker with simply by running the following command:

```
docker-compose up
``` 

This will use some default settings created in the `docker-compose.yml` file located in the root of 
the project. These should be changed before using in any production environments.  

## Adding dependencies
To add a python dependency, run the following commands:

```
pip install <package name>
```

The dependency then needs to be added to the relevant requirements*.txt files as necessary. 

## Stack

- Python 2.7.14
- Django 1.11.13
- DjangoRestFramework 3.8.2 

## Contributing

Please read [CONTRIBUTING.md](https://gist.github.com/kyle-ssg/c36a03aebe492e45cbd3eefb21cb0486) 
for details on our code of conduct, and the process for submitting pull requests to us.

## Getting Help

If you encounter a bug or feature request we would like to hear about it. Before you submit an 
issue please search existing issues in order to prevent duplicates. 

## Get in touch

If you have any questions about our projects you can email 
<a href="mailto:projects@solidstategroup.com">projects@solidstategroup.com</a>.

