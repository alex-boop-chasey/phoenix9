# Plan: Bakery site

Type: new
Repo: alex-boop-chasey/bakery-site
Stack: Next.js, Tailwind, pnpm
Style: warm colours, big photos, friendly tone
Sites the app may contact: api.stripe.com, fonts.googleapis.com

## About
A small website for a local bakery: a home page, a menu page and an order form.

## Every step
Keep pages fast and readable on phones. Use British English.

## Step 1: Set up the project
Scaffold a Next.js app with Tailwind and a home page that says "Coming soon".

Done when:
- `pnpm build` finishes without errors
- The home page shows the text "Coming soon"

## Step 2: Add a Stripe test key
For you: yes
Create a Stripe test account and put STRIPE_SECRET_KEY in the project env file.

## Step 3: Menu page
Depends on: 1, 2
Add a /menu page listing the breads from data/menu.json with name and price.

Done when:
- /menu lists every item in data/menu.json
- Each item shows its price in pounds, like £3.50
