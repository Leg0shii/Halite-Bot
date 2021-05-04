from typing import Dict, List, Any

import hlt
import logging
import numpy

from hlt import Game
from hlt.entity import Ship, Planet

game = hlt.Game("Dragon")
logging.info("Starting my Dragon bot!")


class Bot:
    game: Game
    ship: Ship
    planet: Planet

    def __init__(self, _game):
        self.game = _game
        self.map = _game.map
        self.me = self.map.get_me()
        self.id = self.me.id
        self.my_ships = self.me.all_ships()
        self.enemy_ships = []
        for ship in self.map._all_ships():
            if ship.owner.id != self.id:
                self.enemy_ships.append(ship)
        self.planets = self.map.all_planets()
        self.max_distance = numpy.lib.math.sqrt(self.map.width ** 2 + self.map.height ** 2)
        self.max_planet = max(self.planets, key=lambda planet: planet.radius)
        self.max_radius = self.max_planet.radius
        self.max_remaining_resources = self.max_planet.remaining_resources
        self.max_free_docking_spots = self.max_planet.num_docking_spots
        # Penalties
        self.time_penalty = -1
        self.death_penalty = -50
        self.undock_penalty = -30
        # Bonus
        self.conquer_bonus = 20

    def update(self):
        self.map = game.update_map()
        self.my_ships = self.map.get_me().all_ships()
        self.enemy_ships = []
        for ship in self.map._all_ships():
            if ship.owner.id != self.id:
                self.enemy_ships.append(ship)
        self.planets = self.map.all_planets()

    def command_ships(self):
        _command_queue = []
        for ship in self.my_ships:
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                continue

        return _command_queue

    def evaluate_planet(self, ship, planet):
        if planet.owner == self.me and planet.is_full():
            return -1
        distance = self.max_distance - ship.calculate_distance_between(planet)
        return distance

    def attack(self, ship, planet):
        closest_enemy_ship = None
        command = None
        closest_distance = self.max_distance
        while not command:
            for enemy_ship in planet.all_docked_ships():
                enemy_ship_distance = ship.calculate_distance_between(enemy_ship)
                if closest_distance > enemy_ship_distance:
                    closest_enemy_ship = enemy_ship
                    closest_distance = enemy_ship_distance
            command = ship.navigate(
                ship.closest_point_to(closest_enemy_ship),
                self.map,
                speed=hlt.constants.MAX_SPEED,
                max_corrections=180
            )
        return command


bot = Bot(game)
while True:
    bot.update()
    command_queue = bot.command_ships()
    game.send_command_queue(command_queue)
