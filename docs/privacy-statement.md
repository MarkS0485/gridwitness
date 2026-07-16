# GridWitness privacy statement

*Draft. This is the plain-English statement linked from the Home Assistant consent screen. It must be finalised and legally reviewed before any public contributor onboarding.*

## The deal

GridWitness measures the GB electricity grid using sensors you already own. We ask for the least revealing thing that is useful, which is grid frequency, and every step beyond that is an explicit, revocable choice you make. We will never ask for data we cannot justify to you.

## What each thing tells us, and how sensitive it is

**Grid frequency** is the single number that is the same for everyone connected to the GB grid at a given instant. Sharing it tells us nothing about your household, because it is identical whether measured at your house or the house next door. This is the default, and on its own it is genuinely useful.

**Voltage** is a local reading about the feeder your house sits on, not about you. It helps us map where the grid is strong or weak. Low sensitivity.

**Current, power, and power factor** are the sensitive ones, and we want to be honest. Your electrical load reveals a lot about your life: when you are home, when you sleep and wake, when you cook or charge a car. We ask for it only if you actively choose to share it, never bundled with anything else, and we offer coarser options such as a slower cadence or averaged values. The reason we ask at all is that a node sharing its own power becomes self-calibrating. It lets us work out the local grid strength and correct the sensor, which is scientifically valuable especially at the weak edges of the network. If that trade is not worth it to you, do not share it. Frequency alone still helps.

**Weather** (temperature, humidity, wind, pressure, rain, sunshine) is outdoor ambient conditions, not your behaviour. It helps model how weather drives demand and renewable generation. Low sensitivity. The main consideration is that it implies your rough location.

## Location, and how precise you want to be

* Anonymous (default): we derive only a rough region, similar to a grid supply area, from your connection. No address.
* Region: you pick your DNO or grid region from a list. No address.
* Data-share: you enter your postcode so we can place your readings on the network more precisely. Your postcode never leaves our server and is never published. Only a derived area code, a grid supply point or primary substation rather than your street or feeder, is ever attached to the data.

We are honest about the ceiling. Even in data-share mode we can pin your data to a grid supply point or primary substation, not to your individual street cable. We do not have the data to do that, and we will not claim to.

## What we keep private, server-side, and never publish

Your postcode and precise location, the link between a node and you, and your access token, which is kept hashed. Published data carries only a random node id and derived area codes.

## Your rights

* Change or withdraw any consent at any time from the integration's options.
* Delete all your data. The "delete my data" action removes your server record and marks your already contributed data for removal from the research lake.
* Ask us what we hold about you.

## Legal basis and controller

The server operator is the data controller. Processing rests on explicit consent for the sensitive and location channels, and legitimate interest for the non-identifying grid-frequency research. Data is retained under a stated retention policy, and the private database is encrypted at rest.
