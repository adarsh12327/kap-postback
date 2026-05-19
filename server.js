const express = require("express");
const admin = require("firebase-admin");

const app = express();

const firebaseKey = JSON.parse(
process.env.FIREBASE_KEY
);

admin.initializeApp({
  credential:
  admin.credential.cert(
  firebaseKey),

  databaseURL:
  "https://kap-rewards-afb54-default-rtdb.firebaseio.com"
});

const db =
admin.database();


// HOME
app.get("/", (
req, res) => {

res.send(
"KAP Rewards Running");

});


// CLICK ROUTE
app.get("/click",
async (req, res) => {

try {

const uid =
req.query.uid;

const offer =
req.query.offer;

if (!uid
|| !offer) {

return res.send(
"Missing uid or offer");
}


// GET OFFER
const offerSnap =
await db.ref(
`offers/${offer}`)
.once("value");

if (
!offerSnap.exists()
) {

return res.send(
"Offer not found");
}

const offerData =
offerSnap.val();


// SAVE CLICK
const clickId =
Date.now()
.toString();

await db.ref(
`offer_clicks/${clickId}`)
.set({

uid: uid,

offer: offer,

reward:
offerData.reward,

status:
"pending",

time:
Date.now()

});


// REDIRECT
res.redirect(
offerData.link);

} catch (e) {

res.send(
e.toString());

}

});


// VERIFY
app.get("/verify",
async (req, res) => {

try {

const clickid =
req.query.clickid;

if (!clickid) {

return res.send(
"Click id missing");
}


const clickSnap =
await db.ref(
`offer_clicks/${clickid}`)
.once("value");

if (
!clickSnap.exists()
) {

return res.send(
"Invalid click");
}

const clickData =
clickSnap.val();

if (
clickData.status
=== "completed"
) {

return res.send(
"Already Claimed");
}


const userRef =
db.ref(
`users/${clickData.uid}/coins`);

const userSnap =
await userRef
.once("value");

let oldCoins = 0;

if (
userSnap.exists()
) {

oldCoins =
parseInt(
userSnap.val()
|| 0);

}

const newCoins =
oldCoins +
parseInt(
clickData.reward
|| 0);

await userRef
.set(newCoins);


await db.ref(
`offer_clicks/${clickid}`)
.update({

status:
"completed"

});

res.send(
"Reward Added");

} catch (e) {

res.send(
e.toString());

}

});


const PORT =
process.env.PORT
|| 3000;

app.listen(
PORT,
() => {

console.log(
"Server Running");

});
