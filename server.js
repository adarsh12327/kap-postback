const express =
require("express");

const admin =
require("firebase-admin");

const app =
express();


// FIREBASE KEY
const firebaseKey =
JSON.parse(
process.env
.FIREBASE_KEY
);


// FIREBASE INIT
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
app.get("/",
(req, res) => {

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

uid:
uid,

offer:
offer,

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


// VERIFY ROUTE
app.get("/verify",
async (req, res) => {

try {

const uid =
req.query.uid;

const offer =
req.query.offer;

if (!uid
|| !offer) {

return res.send(
"Missing data");
}


// FIND PENDING OFFER
const snap =
await db.ref(
"offer_clicks")
.once("value");

let clickid =
null;

let clickData =
null;

snap.forEach(
child => {

const data =
child.val();

if (
data.uid
=== uid
&&
data.offer
=== offer
&&
data.status
=== "pending"
) {

clickid =
child.key;

clickData =
data;
}
});


// NO OFFER
if (!clickid) {

return res.send(
"No pending offer");
}


// ADD COINS
const userRef =
db.ref(
`users/${uid}/coins`);

const userSnap =
await userRef
.once("value");

let oldCoins =
0;

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


// SAVE HISTORY
await db.ref(
`history/${uid}`)
.push()
.set({

type:
"Coin Added",

message:
clickData.offer
.replace(/_/g, " "),

coins:
parseInt(
clickData.reward),

time:
Date.now()

});


// UPDATE STATUS
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


// PORT
const PORT =
process.env.PORT
|| 3000;


// START SERVER
app.listen(
PORT,
() => {

console.log(
"Server Running");

});
