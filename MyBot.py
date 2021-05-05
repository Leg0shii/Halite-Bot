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
        # TODO : Integrate Penalties and Bonus
        # Penalties
        self.time_penalty = -1
        self.death_penalty = -50
        self.undock_penalty = -30
        # Bonus
        self.conquer_bonus = 20

    def update(self, _game_map):
        self.map = _game_map
        self.me = self.map.get_me()
        self.my_ships = self.me.all_ships()
        self.enemy_ships = []
        for ship in self.map._all_ships():
            if ship.owner.id != self.id:
                self.enemy_ships.append(ship)
        self.planets = self.map.all_planets()

    def command_ships(self):
        _command_queue = []
        for ship in self.my_ships:
            navigate_command = None
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                continue
            interesting_planet = None
            highest_priority = 0
            for planet in self.planets:
                priority = self.evaluate_planet(ship, planet)
                if priority > highest_priority:
                    interesting_planet = planet
                    highest_priority = priority
            if interesting_planet is None or self.in_proximity_of_enemy(ship):
                navigate_command = self.hunt(ship)
            elif interesting_planet.is_owned() and interesting_planet.owner is not self.me:
                navigate_command = self.attack(ship, interesting_planet)
            elif ship.can_dock(interesting_planet):
                navigate_command = ship.dock(interesting_planet)
            else:
                navigate_command = ship.navigate(
                    ship.closest_point_to(interesting_planet),
                    self.map,
                    speed=hlt.constants.MAX_SPEED)
            if navigate_command is not None:
                _command_queue.append(navigate_command)
        return _command_queue

    def evaluate_planet(self, ship, planet):
        if planet.owner is self.me and planet.is_full():
            return 0
        line_penalty = 1
        for ship_ahead in self.my_ships:
            if ship_ahead.docking_status != ship_ahead.DockingStatus.UNDOCKED:
                continue
            if ship_ahead.calculate_distance_between(planet) < ship.calculate_distance_between(planet):
                line_penalty -= 1 / 3
        distance = 1 - (ship.calculate_distance_between(planet)) / self.max_distance
        remaining_resources = planet.remaining_resources / self.max_remaining_resources
        free_docking_spots = (planet.num_docking_spots - len(planet.all_docked_ships())) / self.max_free_docking_spots
        priority = distance * 3 + remaining_resources * 0.5 + free_docking_spots * 0.5 + line_penalty
        return priority

    def hunt(self, ship):
        closest_enemy_ship = None
        command = None
        closest_distance = self.max_distance
        while command is None:
            for enemy_ship in self.enemy_ships:
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

    def attack(self, ship, planet):
        closest_enemy_ship = None
        command = None
        closest_distance = self.max_distance
        while command is None:
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

    def in_proximity_of_enemy(self, ship):
        for enemy_ship in self.enemy_ships:
            if ship.calculate_distance_between(enemy_ship) < 3 * hlt.constants.SHIP_RADIUS:
                return True
        return False


bot = Bot(game)
while True:
    game_map = game.update_map()
    bot.update(game_map)
    command_queue = bot.command_ships()
    game.send_command_queue(command_queue)
