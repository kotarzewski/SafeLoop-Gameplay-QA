# Vehicle QA methodology

Vehicle handling cannot be validated by screenshots or by an LLM saying it "feels realistic".

SafeLoop Gameplay QA uses repeatable input schedules and telemetry from the actual running scene. Typical tests are:

- straight launch;
- accelerate then full brake;
- steering step at controlled throttle;
- straight-line stability.

Before claiming a calibrated result, define a target profile. Targets may come from the game design specification or a trustworthy reference for the intended vehicle/class. Record provenance and assumptions.

Useful metrics include 0-100 time, speed at brake application, braking distance/time, maximum speed, acceleration/deceleration, steering response time, yaw rate, roll, lateral drift and vertical instability.

A scenario PASS only proves that those specified metrics passed under that test setup and fixed physics rate. Tire model quality, force-feedback feel, varying surfaces, load transfer, aero and edge cases require additional scenarios if they matter to the project.
