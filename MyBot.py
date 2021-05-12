import hlt
import logging
import numpy

from hlt import Game
from hlt.entity import Ship, Planet, Position

game = hlt.Game("Dragon")
logging.info("Starting my Destroyer bot!")


# Checks if point1 is inside a radius of point2
def in_radius_of_point(point1, point2, radius):
    dist = numpy.sqrt((point1[0] - point2.x) ** 2 + (point1[1] - point2.y) ** 2)
    if dist <= radius:
        return True
    return False


class Bot:
    game: Game
    ship: Ship
    planet: Planet

    # Get all the data the first time
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

    # Update the data each round
    def update(self, _game_map):
        self.map = _game_map
        self.me = self.map.get_me()
        self.my_ships = self.me.all_ships()
        self.enemy_ships = []
        for ship in self.map._all_ships():
            if ship.owner.id != self.id:
                self.enemy_ships.append(ship)
        self.planets = self.map.all_planets()

    # Main commanding method
    def command_ships(self):
        _command_queue = []
        for ship in self.my_ships:
            # Leave non undocked ships alone
            if ship.docking_status != ship.DockingStatus.UNDOCKED:
                if not ship.planet.remaining_resources > 0:
                    _command_queue.append(ship.undock())
                    continue
                continue
            # Check if this ship would want to dodge incoming collision
            dodge_command = self.check_if_dodge(ship)
            if dodge_command:
                _command_queue.append(dodge_command)
                continue
            # Check if ship would want to defend the closest planet
            defend_command = self.check_if_defend(ship)
            if defend_command:
                _command_queue.append(defend_command)
                continue
            # MAIN LOGIC
            # Get an interesting planet
            interesting_planet = self.determine_interesting_planet(ship)
            # If None (by construction of evaluate_planet if you for example own all planets)
            # or if that ship is close to an enemy ship
            if interesting_planet is None or self.in_proximity_of_enemy(ship):
                # Hunt down the closest enemy ship
                navigate_command = self.hunt(ship)
            # Else if the planet is owned by an enemy
            elif interesting_planet.is_owned() and interesting_planet.owner is not self.me:
                # Attack the closest docked ship of that planet
                navigate_command = self.attack(ship, interesting_planet)
            # Else dock if possible
            elif ship.can_dock(interesting_planet) and (
                    interesting_planet.owner == self.me or not interesting_planet.is_owned()):
                navigate_command = ship.dock(interesting_planet)
            # Else navigate towards that interesting planet
            else:
                navigate_command = ship.navigate(
                    ship.closest_point_to(interesting_planet),
                    self.map,
                    speed=hlt.constants.MAX_SPEED)
            if navigate_command is not None:
                _command_queue.append(navigate_command)
        return _command_queue

    # Main function for evaluating planets and determining an for the ship interesting one
    def evaluate_planet(self, ship, planet):
        # If it's my planet and if I can't dock any more ships
        if planet.owner is self.me and planet.is_full():
            # It is an uninteresting planet
            return 0
        # If the planet has no remaining resources
        if not planet.remaining_resources > 0:
            # The planet is uninteresting
            return 0
        # The closer to the center, the more important. Strategic 'castle'
        distance_to_center = 1 - planet.calculate_distance_between(
            Position(self.map.width / 2, self.map.height / 2)) / self.max_distance
        # This describes a penalty for navigating towards a planet if some other ships of mine already
        # go there. The more ships navigate towards a planet and form a line, hence the name, the bigger
        # the penalty. Note that a penalty means adding less to or even subtracting from the final planets
        # priority
        line_penalty = 1
        for ship_ahead in self.my_ships:
            if ship_ahead.docking_status != ship_ahead.DockingStatus.UNDOCKED:
                continue
            if ship_ahead.calculate_distance_between(planet) < ship.calculate_distance_between(planet):
                line_penalty -= 1 / 3
        # The closer a planet, the more important it becomes
        distance = 1 - (ship.calculate_distance_between(planet)) / self.max_distance
        # Same with all these
        remaining_resources = planet.remaining_resources / self.max_remaining_resources
        free_docking_spots = (planet.num_docking_spots - len(planet.all_docked_ships())) / self.max_free_docking_spots
        enemy_planet = 0
        if planet.is_owned() and planet.owner != self.me:
            if ship.calculate_distance_between(planet) < self.max_distance / 4:
                enemy_planet = 1 - len(planet.all_docked_ships()) / planet.num_docking_spots
        # Weighted priority
        priority = distance * 3 + enemy_planet * 1 + remaining_resources * 0.5 + free_docking_spots * 0.5 \
                   + line_penalty * 1 + distance_to_center * 1
        return priority

    # Hunt down the closest enemy ship
    def hunt(self, ship):
        closest_enemy_ship = None
        command = None
        closest_distance = self.max_distance
        # Determine the closest enemy ship
        for enemy_ship in self.enemy_ships:
            enemy_ship_distance = ship.calculate_distance_between(enemy_ship)
            if closest_distance > enemy_ship_distance:
                closest_enemy_ship = enemy_ship
                closest_distance = enemy_ship_distance
        # Navigate towards it. This will attack it if it reaches its radius.
        command = ship.navigate(
            ship.closest_point_to(closest_enemy_ship),
            self.map,
            speed=hlt.constants.MAX_SPEED
        )
        return command

    # Same as hunting, except now attack the closest docked ship of a given planet
    def attack(self, ship, planet):
        closest_enemy_ship = None
        closest_distance = self.max_distance
        for enemy_ship in planet.all_docked_ships():
            enemy_ship_distance = ship.calculate_distance_between(enemy_ship)
            if closest_distance > enemy_ship_distance:
                closest_enemy_ship = enemy_ship
                closest_distance = enemy_ship_distance
        command = ship.navigate(
            ship.closest_point_to(closest_enemy_ship),
            self.map,
            speed=hlt.constants.MAX_SPEED
        )
        return command

    # Gives a ship an option to detect close ships
    def in_proximity_of_enemy(self, ship):
        for enemy_ship in self.enemy_ships:
            if ship.calculate_distance_between(enemy_ship) < 5 * hlt.constants.WEAPON_RADIUS:
                return True
        return False

    # Returns a defend command
    def check_if_dodge(self,ship):
        dodge_command = None
        # If the ship is too close to another of my ships
        for too_close_ship in self.my_ships:
            if ship is too_close_ship:
                continue
            if ship.calculate_distance_between(too_close_ship) < hlt.constants.WEAPON_RADIUS / 2:
                dodge_command = ship.navigate(
                    Position(ship.x + (ship.x - too_close_ship.x), ship.y - (ship.y - too_close_ship.y)),
                    self.map,
                    speed=hlt.constants.MAX_SPEED
                )
        return dodge_command

    # Returns an interesting planet
    def determine_interesting_planet(self, ship):
        interesting_planet = None
        highest_priority = 0
        # Determine an interesting planet
        for planet in self.planets:
            priority = self.evaluate_planet(ship, planet)
            if priority > highest_priority:
                interesting_planet = planet
                highest_priority = priority
        return interesting_planet

    # Returns a defend command (Attack closest enemy ship) if conditions are met
    def check_if_defend(self, ship):
        # Base is the closest planet
        closest_planet = self.get_closest_planet(ship)
        closest_enemy_ship = None
        command = None
        closest_distance = self.max_distance
        # Get the closest enemy ship and distance of that closest planet
        for enemy_ship in self.enemy_ships:
            enemy_ship_distance = closest_planet.calculate_distance_between(enemy_ship)
            if closest_distance > enemy_ship_distance:
                closest_enemy_ship = enemy_ship
                closest_distance = enemy_ship_distance
        # If I own the closest planet and an enemy ship is within 3 times its radius distance
        if closest_planet.owner == self.me and closest_distance < closest_planet.radius * 3:
            # Defend the planet
            command = ship.navigate(
                ship.closest_point_to(closest_enemy_ship),
                self.map,
                speed=hlt.constants.MAX_SPEED
            )
        return command

    # Returns closest planet
    def get_closest_planet(self, ship):
        min_planet = None
        min_distance = self.max_distance
        for planet in self.planets:
            if min_distance > ship.calculate_distance_between(planet):
                min_planet = planet
                min_distance = ship.calculate_distance_between(planet)
        return min_planet

    # Moves the ship around
    def ship_move(self, ship, target, radius):
        angle = ship.calculate_angle_between(ship.closest_point_to(target))
        speed = hlt.constants.MAX_SPEED
        distance = ship.calculate_distance_between(target)

        if ship.docking_status == ship.DockingStatus.DOCKED:
            return None

        # Checks if ship is already in radius of object
        if not in_radius_of_point((ship.x, ship.y), target, radius):
            # Checks if distance between object is smaller then 7, if so, move only half of the speed
            if distance < speed:
                move_command = ship.thrust(distance, angle)
                return move_command
            else:
                move_command = ship.thrust(speed, angle)
                updated_ship_posx = speed * numpy.cos(angle) + ship.x
                updated_ship_posy = speed * numpy.sin(angle) + ship.y
            # Check if there are any planets in the way, if so, adjust angle by 1 degree
            for planet in self.map.all_planets():
                counter = 0
                while in_radius_of_point((updated_ship_posx, updated_ship_posy), planet, planet.radius) \
                        and counter < 100:
                    angle = angle + 1
                    updated_ship_posx = speed * numpy.cos(angle) + ship.x
                    updated_ship_posy = speed * numpy.sin(angle) + ship.y
                    counter = counter + 1
                    move_command = ship.thrust(speed, angle)

            counter = 0
            for too_close_ship in self.my_ships:
                logging.debug("Ship too close!")
                while in_radius_of_point((updated_ship_posx, updated_ship_posy), too_close_ship, 0) and counter < 100:
                    angle = angle + 1
                    updated_ship_posx = speed * numpy.cos(angle) + ship.x
                    updated_ship_posy = speed * numpy.sin(angle) + ship.y
                    counter = counter + 1
                    move_command = ship.thrust(speed, angle)

            return move_command
        return None


# Basic turn loop. First update our bot, then fetch the commands and send them to the halite engine
bot = Bot(game)
while True:
    game_map = game.update_map()
    bot.update(game_map)
    command_queue = bot.command_ships()
    game.send_command_queue(command_queue)
