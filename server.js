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


// CLICK TRACKING
app.get("/click",
async (req, res) => {

try {

const uid =
req.query.uid;

const offer =
req.query.offer;

if (!uid ||
!offer) {

return res.send(
"Missing uid or offer");
}


// GET OFFER DATA
const offerSnap =
await db.ref(
`offers/${offer}`)
.once("value");

if (!offerSnap.exists()) {

return res.send(
"Offer not found");
}

const offerData =
offerSnap.val();


// GENERATE CLICK ID
const clickId =
Date.now().toString();


// SAVE CLICK
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


// REDIRECT TO PLAY STORE
return res.redirect(
offerData.link);

} catch (e) {

res.send(
e.toString());
}

});


// VERIFY INSTALL
app.get("/verify",
async (req, res) => {

try {

const clickid =
req.query.clickid;

if (!clickid) {

return res.send(
"Click ID missing");
}


// CLICK DATA
const clickSnap =
await db.ref(
`offer_clicks/${clickid}`)
.once("value");

if (!clickSnap.exists()) {

return res.send(
"Invalid Click ID");
}

const clickData =
clickSnap.val();


// ALREADY CLAIMED
if (
clickData.status
=== "completed"
) {

return res.send(
"Already Claimed");
}


// USER COINS
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
.toString());
}


// ADD COINS
const newCoins =
oldCoins +
parseInt(
clickData.reward);

await userRef
.set(newCoins);


// COMPLETE STATUS
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

app.listen(PORT,
() => {

console.log(
"Server Running");

});req,
res) => {

try {

const uid =
req.query.uid;

const reward =
parseInt(
req.query.reward
|| 0);

if(!uid ||
!reward) {

return res.send(
"Missing uid or reward");
}

const userRef =
db.ref(
`users/${uid}/coins`);

const snap =
await userRef.once(
"value");

const oldCoins =
parseInt(
snap.val()
|| 0);

await userRef.set(
oldCoins
+ reward);

res.send(
"Reward Added");

} catch(e) {

res.send(
e.toString());
}
});

app.listen(
3000,
() => {

console.log(
"Server Started");
});
