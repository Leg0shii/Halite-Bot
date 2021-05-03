from typing import Dict, List, Any

import hlt
import logging

# My custom game phases as an enum

from enum import Enum

from hlt.entity import Ship


class Phase(Enum):
    beginning = 0
    fighting = 1
    hunting = 2


# GAME START
game = hlt.Game("Dragon")
logging.info("Starting my Dragon bot!")

# Stores current game state. Start game with beginning phase
game_state = Phase.beginning

# Stores a priority queue for each of my ships using a dict
ships_priority_queues: dict[Ship, list[Any]] = {}

while True:
    # TURN START
    # Update the map for the new turn and get the latest version
    game_map = game.update_map()
    # Here we define the set of commands to be sent to the Halite engine at the end of the turn
    command_queue = []

    # Determine biggest planets
    biggest_planets = sorted(game_map.all_planets(), key=lambda x: x.radius, reverse=True)

    # add my ships to priority queue if not already present
    ships_priority_queues_copy = {}
    for ship in game_map.get_me().all_ships():
        if ship not in ships_priority_queues.keys():
            ships_priority_queues_copy[ship] = []
        else:
            ships_priority_queues_copy[ship] = ships_priority_queues[ship]
    ships_priority_queues = ships_priority_queues_copy

    # During the beginning phase
    if game_state == Phase.beginning:
        # For all my Ships
        for ship in game_map.get_me().all_ships():
            navigate_command = None
            # Determine closest planets and put them into a list
            all_planets_by_distance = game_map.nearby_planets_with_distance(ship)
            closest_planets = []
            for k in sorted(all_planets_by_distance.keys()):
                closest_planets.append(all_planets_by_distance.get(k))
            # If the ship is docked
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                # Skip this ship
                continue

            # Check for each closest planet
            for planet in closest_planets:
                # If the planet is already full
                if planet.is_full():
                    # Skip it
                    continue
                # If the ship can dock
                if ship.can_dock(planet):
                    # Then dock
                    command_queue.append(ship.dock(planet))
                    break
                # Else if the planet is owned by enemy
                elif planet.is_owned() and planet.owner != game_map.get_me():
                    # Destroy a docked ship
                    navigate_command = ship.navigate(
                        ship.closest_point_to(planet.all_docked_ships()[0]),
                        game_map,
                        speed=int(hlt.constants.MAX_SPEED))
                else:
                    # Else navigate towards this planet
                    navigate_command = ship.navigate(
                        ship.closest_point_to(planet),
                        game_map,
                        speed=int(hlt.constants.MAX_SPEED))
                if navigate_command:
                    command_queue.append(navigate_command)
                    break
            # If the closest planet is occupied start fighting
            if closest_planets[0].is_full():
                game_state = Phase.fighting
    elif game_state == Phase.fighting:
        # For every ship that I control
        for ship in ships_priority_queues.keys():
            navigate_command = None
            # If this ship doesn't have priority planets
            if not ships_priority_queues[ship]:
                ship.create_priority_queue_for_ship(game_map, ships_priority_queues, biggest_planets)

            # If the ship is docked and resources are empty
            if ship.docking_status == ship.DockingStatus.DOCKED and not ship.__getattribute__(
                    "planet").remaining_resources > 0:
                # Undock
                command_queue.append(ship.undock())
                continue
            # If ship is not undocked (and resources are present)
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                # Keep docked
                continue

            # For each planet in the game by priority
            for planet in ships_priority_queues[ship]:
                # If the planet is owned by an enemy
                if planet.is_owned() and planet.owner != game_map.get_me():
                    # Destroy a docked ship
                    navigate_command = ship.navigate(
                        ship.closest_point_to(planet.all_docked_ships()[0]),
                        game_map,
                        speed=int(hlt.constants.MAX_SPEED))
                elif ship.can_dock(planet):
                    # We add the command by appending it to the command_queue
                    command_queue.append(ship.dock(planet))
                    break
                else:
                    # Else the planet must be free to occupy, so fly towards it
                    navigate_command = ship.navigate(
                        ship.closest_point_to(planet),
                        game_map,
                        speed=int(hlt.constants.MAX_SPEED))
                if navigate_command:
                    command_queue.append(navigate_command)
                    break
            # If there are less than 3 planets in a ship priority queue, begin the hunting phase
            if len(ships_priority_queues[ship]) < 3:
                game_state = Phase.hunting
            ships_priority_queues[ship] = []
    # In the hunting phase, all ships seek out enemy ships and try to destroy them
    elif game_state == Phase.hunting:
        for ship in game_map.get_me().all_ships():
            navigate_command = None
            # Leave ships which produce ships alone and undock those attached to resource-less planets
            if ship.docking_status == ship.DockingStatus.DOCKED \
                    and not ship.__getattribute__("planet").remaining_resources > 0:
                command_queue.append(ship.undock())
                continue
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                continue
            # Determine list of nearby enemy ships sorted by distance
            all_enemy_ships_by_distance = game_map.nearby_enemy_ships_by_distance(ship)
            closest_enemy_ships = []
            for k in sorted(all_enemy_ships_by_distance.keys()):
                closest_enemy_ships.append(all_enemy_ships_by_distance.get(k))
            # Attack one of the closest ships
            for enemy_ship in closest_enemy_ships:
                navigate_command = ship.navigate(
                    ship.closest_point_to(enemy_ship),
                    game_map,
                    speed=int(hlt.constants.MAX_SPEED))
                if navigate_command:
                    break
            if navigate_command:
                command_queue.append(navigate_command)

    # Send our set of commands to the Halite engine for this turn
    game.send_command_queue(command_queue)
    # TURN END
# GAME END
