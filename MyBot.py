"""
Welcome to your first Halite-II bot!

This bot's name is Settler. It's purpose is simple (don't expect it to win complex games :) ):
1. Initialize game
2. If a ship is not docked and there are unowned planets
2.a. Try to Dock in the planet if close enough
2.b If not, go towards the planet

Note: Please do not place print statements here as they are used to communicate with the Halite engine. If you need
to log anything use the logging module.
"""
# Let's start by importing the Halite Starter Kit so we can interface with the Halite engine
import hlt
# Then let's import the logging module so we can print out information
import logging

# GAME START
# Here we define the bot's name as Settler and initialize the game, including communication with the Halite engine.
game = hlt.Game("Dragon")
# Then we print our start message to the logs
logging.info("Dragon")

while True:
    # TURN START
    # Update the map for the new turn and get the latest version
    game_map = game.update_map()

    # Here we define the set of commands to be sent to the Halite engine at the end of the turn
    command_queue = []
    available_planet = game_map.all_planets()
    targeted_planet = []
    plNum = 0
    # For every ship that I control
    for ship in game_map.get_me().all_ships():
        if ship.docking_status != ship.DockingStatus.UNDOCKED:
            continue  # TODO : support other ships in war

        no_target = [plan for plan in available_planet if plan not in targeted_planet]

        closestplanet = no_target[0]
        for planet in no_target:
            if planet.calculate_distance_between(ship) < closestplanet.calculate_distance_between(ship):
                closestplanet = planet
        targeted_planet.append(closestplanet)

        if ship.can_dock(closestplanet):
            command_queue.append(ship.dock(closestplanet))
        else:
            command_queue.append(
                ship.navigate(
                    ship.closest_point_to(closestplanet),
                    game_map,
                    speed=int(hlt.constants.MAX_SPEED/2),
                    ignore_ships=False
                )
            )
            plNum = plNum + 1
    # Send our set of commands to the Halite engine for this turn
    game.send_command_queue(command_queue)
    # TURN END
# GAME END

