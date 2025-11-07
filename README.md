# websockets-tutorial

Connect 4 tutorial to learn some websockets!

## Deploying to Heroku

1. Log in to Heroku and create an app (replace `<app-name>` with your own name):
   ```bash
   heroku login
   heroku create <app-name>
   ```
2. Set the Heroku git remote if it isn't configured automatically:
   ```bash
   heroku git:remote -a <app-name>
   ```
3. Push the branch you want to deploy:
   ```bash
   git push heroku HEAD:main
   ```
   If your Heroku app still uses the `master` branch, push to `master` instead.
4. Once the build completes, open the deployed app:
   ```bash
   heroku open
   ```
5. To review logs (useful for debugging):
   ```bash
   heroku logs --tail
   ```

The Heroku Python buildpack detects the `Procfile` and `requirements.txt` in this repository and starts the application with `python app.py`, which serves both the static assets and the WebSocket server on the port provided by Heroku.
