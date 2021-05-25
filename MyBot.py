import hlt
import logging
import numpy
import math
import time

from hlt import Game
from hlt.entity import Ship, Planet, Position
from hlt import constants

game = hlt.Game("Dragon")

ship_pos_dict = {}


# Checks if point1 is inside a radius of point2
def in_radius_of_point(point1, point2, radius):
    dist = numpy.sqrt((point1.x - point2.x) ** 2 + (point1.y - point2.y) ** 2)
    if dist <= radius:
        return True
    return False


def calc_dist(point1, point2):
    dist = numpy.sqrt((point1.x - point2.x) ** 2 + (point1.y - point2.y) ** 2)
    return dist


def calc_update_pos(ship, speed, angle):
    return Position(speed * numpy.cos(numpy.radians(angle)) + ship.x,
                    speed * numpy.sin(numpy.radians(angle)) + ship.y)


def calc_midpoint(pos1, pos2):
    x_m = (numpy.abs(pos1.x - pos2.x) / 2) + numpy.minimum(pos1.x, pos2.x)
    y_m = (numpy.abs(pos1.y - pos2.y) / 2) + numpy.minimum(pos1.y, pos2.y)
    return Position(x_m, y_m)


def get_offset_points(pos1, pos2, middle, offset):
    new_x_1 = middle.x + offset
    new_x_2 = middle.x - offset
    m = (numpy.abs(pos1.x - pos2.x) / numpy.abs(pos1.y - pos2.y))
    new_y_1 = m * new_x_1 + (m * middle.x) * (-1) + middle.y
    new_y_2 = m * new_x_2 + (m * middle.x) * (-1) + middle.y
    return [Position(new_x_1, new_y_1), Position(new_x_2, new_y_2)]


def takeFirst(elem):
    return elem[0]


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
        self.turn = 0
        self.starting_position = Position(0, 0)
        self.my_ships_ids = []
        for ship in self.my_ships:
            self.my_ships_ids.append(ship.id)
        # TODO : Integrate Penalties and Bonus
        # Penalties
        self.time_penalty = -1
        self.death_penalty = -50
        self.undock_penalty = -30
        # Bonus
        self.conquer_bonus = 20

    # Update the data each round
    def update(self, _game_map):
        if self.turn < 1:
            self.starting_position = Position(self.my_ships[0].x, self.my_ships[0].y)
        self.map = _game_map
        self.me = self.map.get_me()
        self.my_ships = self.me.all_ships()
        self.my_ships_ids = []
        for ship in self.my_ships:
            self.my_ships_ids.append(ship.id)
        self.enemy_ships = []
        for ship in self.map._all_ships():
            if ship.owner.id != self.id:
                self.enemy_ships.append(ship)
        self.planets = self.map.all_planets()
        self.turn += 1
        saved_ids = []
        for ship_id in ship_pos_dict.keys():
            if ship_id not in self.my_ships_ids:
                saved_ids.append(ship_id)
        for saved_id in saved_ids:
            ship_pos_dict.pop(saved_id)

    # Main commanding method
    def command_ships(self):
        _command_queue = []
        if self.turn < 100:
            self.my_ships: []
            for ship in self.my_ships:
                if self.my_ships.index(ship) == 0 and self.check_if_rushed(ship):
                    mitigate_command = self.mitigate_rush(ship)
                    if mitigate_command:
                        _command_queue.append(mitigate_command)
                else:
                    command = self.get_command(ship)
                    if command:
                        _command_queue.append(command)
            return _command_queue
        for ship in self.my_ships:
            navigate_command = self.get_command(ship)
            if navigate_command is not None:
                _command_queue.append(navigate_command)
        return _command_queue

    def get_command(self, ship):
        # Leave non undocked ships alone
        if ship.docking_status != ship.DockingStatus.UNDOCKED:
            if not ship.planet.remaining_resources > 0:
                return ship.undock()
        # Check if ship would want to defend the closest planet
        defend_command = self.check_if_defend(ship)
        if defend_command:
            return defend_command
        # MAIN LOGIC
        # Get an interesting planet
        interesting_planet = self.determine_interesting_planet(ship)
        # If None (by construction of evaluate_planet if you for example own all planets)
        # or if that ship is close to an enemy ship
        if interesting_planet is None or self.in_proximity_of_enemy(ship):
            # Hunt down the closest enemy ship
            return self.hunt(ship)
        # Else if the planet is owned by an enemy
        if interesting_planet.is_owned() and interesting_planet.owner is not self.me:
            # Attack the closest docked ship of that planet
            return self.attack(ship, interesting_planet)
        # Else dock if possible
        if ship.can_dock(interesting_planet) and (
                interesting_planet.owner == self.me or not interesting_planet.is_owned()):
            return ship.dock(interesting_planet)
        # Else navigate towards that interesting planet
        return self.ship_move(ship, ship.closest_point_to(interesting_planet))

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
                line_penalty -= 1 / 4
        # The closer a planet, the more important it becomes
        distance = 1 - (ship.calculate_distance_between(planet)) / self.max_distance
        # Same with all these
        remaining_resources = planet.remaining_resources / self.max_remaining_resources
        free_docking_spots = 1 - len(planet.all_docked_ships()) / planet.num_docking_spots
        enemy_planet = 0
        if planet.is_owned() and planet.owner != self.me:
            # Only show interest if planet is close enough
            if ship.calculate_distance_between(planet) < self.max_distance / 4:
                enemy_planet = 1 - len(planet.all_docked_ships()) / planet.num_docking_spots
        unowned_planet = 0
        if not planet.is_owned():
            unowned_planet = 1
        back_planet = 0
        if self.starting_position.calculate_distance_between(Position(planet.x, planet.y)) < self.map.width / 4:
            back_planet = 1
        # Weighted priority
        priority = distance * 1 + enemy_planet * 1 + remaining_resources * 0.1 + free_docking_spots * 0.1 \
                   + line_penalty * 1 + distance_to_center * 0.5 + unowned_planet * 0.05 + back_planet * 1
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
        command = self.ship_move(ship, ship.closest_point_to(closest_enemy_ship))
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
        command = self.ship_move(ship, ship.closest_point_to(closest_enemy_ship))
        return command

    # Gives a ship an option to detect close ships
    def in_proximity_of_enemy(self, ship):
        for enemy_ship in self.enemy_ships:
            if ship.calculate_distance_between(enemy_ship) < 5 * hlt.constants.WEAPON_RADIUS:
                return True
        return False

    def has_obstacle_in_path(self, points, ship):
        obs1 = self.map.obstacles_between(ship, points[0])
        obs2 = self.map.obstacles_between(ship, points[1])
        if len(obs1) == 0:
            return points[0]
        elif len(obs2) == 0:
            return points[1]
        else:
            return None

    # Checks if enemy rushes. Assumes rushing only happens if starting positions are top and bottom.
    def check_if_rushed(self, ship):
        for enemy_ship in self.enemy_ships:
            if ship.calculate_distance_between(enemy_ship) < self.map.height / 2 and len(self.enemy_ships) <= 3:
                return True
        return False

    # Mitigates an enemy rush. Works best if enemy forms squads
    def mitigate_rush(self, ship):
        command = None
        closest_enemy_ship: Ship = None
        closest_distance = self.max_distance
        # Determine closest enemy ship
        for enemy_ship in self.enemy_ships:
            enemy_ship_distance = ship.calculate_distance_between(enemy_ship)
            if closest_distance > enemy_ship_distance:
                closest_enemy_ship = enemy_ship
                closest_distance = enemy_ship_distance
        # If the enemy ship is less than 4 weapon radii, start the circle planet protocol
        if closest_distance > hlt.constants.WEAPON_RADIUS * 4:
            command = self.ship_move(ship, ship.closest_point_to(closest_enemy_ship))
        # Else move towards the enemy ship to bait it
        elif self.turn < 10:
            command = self.ship_move(ship, self.starting_position)
        else:
            command = self.circle_planet(ship, closest_enemy_ship)
        return command

    # Circles the closest viable planet counter clock wise and baits enemy ship to follow you endlessly
    def circle_planet(self, ship, enemy_ship):
        closest_planet: Planet = self.get_viable_planet_for_bait(ship)
        if closest_planet is None:
            return self.hunt(ship)
        # Calculate some stuff used for equations
        distance_to_planet_ship = ship.calculate_distance_between(closest_planet)
        distance_to_planet_enemy_ship = closest_planet.calculate_distance_between(enemy_ship)
        distance_between_ships = ship.calculate_distance_between(enemy_ship)
        # Determine angle at which to circle planet. Uses isosceles triangle calculations
        flying_angle_normal_speed = math.acos((hlt.constants.MAX_SPEED / 2) / (closest_planet.radius + 2))
        flying_angle_normal_speed = math.degrees(flying_angle_normal_speed)
        flying_angle_less_speed = math.acos(((hlt.constants.MAX_SPEED / 1.5) / 2) / (closest_planet.radius + 2))
        flying_angle_less_speed = math.degrees(flying_angle_less_speed)
        # If ship hasn't reached the planet to circle, move towards it
        if ship.calculate_distance_between(closest_planet) > (closest_planet.radius + hlt.constants.MAX_SPEED * 1.5):
            command = self.ship_move(ship, ship.closest_point_to(closest_planet))
        else:
            # Triggers different flying speeds to compensate for bots that circle suboptimal. Uses cosine law
            trigger_angle = math.acos(
                (distance_to_planet_enemy_ship ** 2 - distance_to_planet_ship ** 2 - distance_between_ships ** 2) / (
                        -2 * distance_to_planet_ship * distance_between_ships))
            trigger_angle = math.degrees(trigger_angle)
            # Trigger angle is then the angle between points: planet center, enemy_ship and my ship
            # Quick explanation: the farther behind the enemy ship is, the smaller is the trigger angle
            if trigger_angle > 30:
                # Circle at full speed
                command = ship.thrust(hlt.constants.MAX_SPEED,
                                      (ship.calculate_angle_between(closest_planet) + flying_angle_normal_speed) % 360)
            else:
                # Circle at slower speed
                command = ship.thrust(hlt.constants.MAX_SPEED / 1.5,
                                      (ship.calculate_angle_between(closest_planet) + flying_angle_less_speed) % 360)
        return command

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
            enemy_ship_distance = enemy_ship.calculate_distance_between(closest_planet)
            if closest_distance > enemy_ship_distance:
                closest_enemy_ship = enemy_ship
                closest_distance = enemy_ship_distance
        # If I own the closest planet and an enemy ship is within 3 times its radius distance
        if closest_planet.owner == self.me and closest_distance < hlt.constants.MAX_SPEED * 3 + closest_planet.radius:
            # Defend the planet
            command = self.ship_move(ship, ship.closest_point_to(closest_enemy_ship))
        if closest_planet.owner == self.me and ship.calculate_distance_between(
                Position(self.map.width / 2,
                         self.map.height / 2)) < 4 * hlt.constants.MAX_SPEED and closest_distance < hlt.constants.MAX_SPEED * 5 + closest_planet.radius:
            command = self.ship_move(ship, ship.closest_point_to(closest_enemy_ship))
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

    def get_viable_planet_for_bait(self, ship):
        min_planet = None
        min_distance = self.max_distance
        for planet in self.planets:
            if planet.calculate_distance_between(Position(self.map.width / 2, self.map.height / 2)) < 20:
                continue
            if self.map.width / 3 < planet.x < self.map.width - self.map.width / 3:
                continue
            if planet.is_owned():
                continue
            if min_distance > ship.calculate_distance_between(planet):
                min_planet = planet
                min_distance = ship.calculate_distance_between(planet)
        return min_planet

    def ship_move(self, ship: Ship, target: Position):
        distance_to_target = ship.calculate_distance_between(target)
        angle = ship.calculate_angle_between(target)
        speed = constants.MAX_SPEED

        obstacles_on_path = game_map.obstacles_between(ship, target)
        logging.debug("ShipNR: " + str(ship.id) + " || OBSTACLES: " + str(obstacles_on_path))

        # If no obstacles on the way, fly straight
        if len(obstacles_on_path) == 0:
            # If you are already closer then 8, fly with slower speed
            if distance_to_target < hlt.constants.MAX_SPEED:
                logging.debug(
                    "ShipNR: " + str(ship.id) + " || Thrust: " + str(distance_to_target) + " with Angle: " + str(angle))
                ship_pos_dict[ship.id] = calc_update_pos(ship, distance_to_target, angle)
                return ship.thrust(distance_to_target, angle)
            # Fly straight as fast as possible
            else:
                logging.debug("ShipNR: " + str(ship.id) + " || Thrust: " + str(speed) + " with Angle: " + str(angle))
                ship_pos_dict[ship.id] = calc_update_pos(ship, speed, angle)
                return ship.thrust(speed, angle)
        else:
            ship_targets = []
            org_angle = angle
            # get 10 angles away from straight line on both sides
            for i in range(10):
                speed = 1
                for j in range(6):
                    angle = ((((-1) ** i) * numpy.floor(i / 2) * 180 / 10 + org_angle) % 360)
                    # calc next position
                    vec = self.create_vector_by_angle(angle, speed)
                    possible_target = Position(ship.x + vec[0], ship.y + vec[1])
                    # save all positions that are outside of a planet or enemy
                    if len(game_map.obstacles_between(ship, possible_target)) > 0:
                        break
                    dist_to_poss_target = target.calculate_distance_between(possible_target)
                    ship_targets.append([dist_to_poss_target, possible_target, speed])
                    speed = speed + 1
            # sort these so the one with shortest distance to goal is first
            # if it cant find any nearest targets, do nothing
            if len(ship_targets) == 0:
                logging.debug("COULDNT FIND ANYTHING HELP1")
                ship_pos_dict[ship.id] = Position(ship.x, ship.y)
                return None
            ship_targets.sort(key=lambda x: x[0])
            ship_pos_dict[ship.id] = ship_targets[0][1]
            better_speed = ship_targets[0][2]
            vec1 = self.create_vector_by_positions(Position(ship.x, ship.y),
                                                   Position(ship_pos_dict[ship.id].x, ship_pos_dict[ship.id].y))
            # look through all ships
            for ship_id in ship_pos_dict.keys():
                ships = self.me.get_ship(ship_id)
                ships: Ship
                ships_end_position = ship_pos_dict.get(ships.id)
                vec2 = self.create_vector_by_positions(Position(ships.x, ships.y),
                                                       Position(ships_end_position.x, ships_end_position.y))
                if ships.id == ship.id:
                    continue
                if ship.calculate_distance_between(ships) > hlt.constants.MAX_SPEED * 2.5:
                    continue
                counter = 0
                # if position is the same, then iterate through saved positions of this ship
                while self.check_intersection(Position(ship.x, ship.y), vec1,
                                              Position(ships.x, ships.y), vec2, hlt.constants.SHIP_RADIUS):
                    # logging.debug(str("COUNTER: " + str(counter)))
                    # logging.debug("Checking: " + str(ship_pos_dict[ship].x) + " " + str(ship_pos_dict[ship].y))
                    # logging.debug("Still intersecting with " + str(ships.id))
                    # if cant find any, stop
                    if counter == len(ship_targets):
                        ship_pos_dict[ship.id] = Position(ship.x, ship.y)
                        logging.debug("COULDNT FIND ANYTHING HELP2" + " || With counter: " + str(counter))
                        return None
                    ship_pos_dict[ship.id] = ship_targets[counter][1]
                    better_speed = ship_targets[counter][2]
                    new_angle = ship.calculate_angle_between(ship_pos_dict[ship.id])
                    vec1 = self.create_vector_by_angle(new_angle, better_speed)
                    counter = counter + 1
            new_angle = ship.calculate_angle_between(ship_pos_dict[ship.id])
            # use the one with shortest distance to goal as next target
            logging.debug("ShipNR: " + str(ship.id) + " || Found New Command: " + " || Thrust: " + str(
                better_speed) + " with Angle: " + str(new_angle))
            return ship.thrust(better_speed, new_angle)

    def ship_move2(self, ship, target):
        distance_to_target = ship.calculate_distance_between(target)
        angle = round(ship.calculate_angle_between(ship.closest_point_to(target)))
        speed = constants.MAX_SPEED

        obstacles_on_path = game_map.obstacles_between(ship, target)
        logging.debug("ShipNR: " + str(ship.id) + " || OBSTACLES: " + str(obstacles_on_path))

        # If ship is already closer then 0.5 units then dont do anything
        # if distance_to_target < 0.5:
        #     logging.debug("ShipNR: " + str(ship.id) + " || No movement")
        #     ship_pos_dict[ship] = Position(ship.x, ship.y)
        #     logging.debug("COULDNT FIND ANYTHING HELP0")
        #     return None

        # If no obstacles on the way, fly straight
        if len(obstacles_on_path) == 0:
            # If you are already closer then 7, fly with slower speed
            if distance_to_target < 7:
                smaller_speed = numpy.ceil(distance_to_target)
                logging.debug(
                    "ShipNR: " + str(ship.id) + " || Thrust: " + str(smaller_speed) + " with Angle: " + str(angle))
                ship_pos_dict[ship] = calc_update_pos(ship, smaller_speed, angle)
                return ship.thrust(smaller_speed, angle)
            # Fly straight as fast as possible
            else:
                logging.debug("ShipNR: " + str(ship.id) + " || Thrust: " + str(speed) + " with Angle: " + str(angle))
                ship_pos_dict[ship] = calc_update_pos(ship, speed, angle)
                return ship.thrust(speed, angle)
        else:
            ship_targets = []
            org_angle = angle
            # get 10 angles away from straight line on both sides
            start_time = time.time()
            tries = 20
            for i in range(tries):
                speed = 7
                for j in range(1):
                    if i < tries * 0.85:
                        angle = ((((-2) ** i) * numpy.floor(i / 2) + org_angle) % 360)
                    elif tries * 0.85 < i < tries * 0.9:
                        angle = ((((-2) ** i) * numpy.floor(i / 2) + (org_angle + 90)) % 360)
                    elif tries * 0.9 < i < tries * 0.95:
                        angle = ((((-2) ** i) * numpy.floor(i / 2) + (org_angle + 180)) % 360)
                    else:
                        angle = ((((-2) ** i) * numpy.floor(i / 2) + (org_angle + 270)) % 360)
                    # calc next position
                    possible_target = calc_update_pos(ship, speed, angle)
                    # save all positions that are outside of a planet or enemy
                    if (not in_radius_of_point(possible_target, obstacles_on_path[0], obstacles_on_path[0].radius + 0.6)
                        and not game_map.obstacles_between(ship, possible_target)) \
                            or self.is_enemy_ship(obstacles_on_path[0]):
                        dist_to_poss_targ = calc_dist(possible_target, target)
                        ship_targets.append((dist_to_poss_targ, possible_target, speed))
                    speed = speed + 1
            logging.debug("TIME1 : " + str(time.time() - start_time))

            # if it cant find any nearest targets, do nothing
            if len(ship_targets) == 0:
                logging.debug("COULDNT FIND ANYTHING HELP1")
                ship_pos_dict[ship] = Position(ship.x, ship.y)
                return None
            # sort these so the one with shortest distance to goal is first
            ship_targets.sort(key=takeFirst)
            ship_pos_dict[ship] = ship_targets[0][1]
            # repeat for loop until you find a position that isnt used by other ship
            better_speed = ship_targets[0][2]
            restart_counter = 0
            restart = True
            start_time = time.time()
            while restart and restart_counter < 5:
                # resets the while loop to be escaped
                restart = False
                # look through all ships
                for ships in ship_pos_dict.keys():
                    counter = 1
                    # if position is the same, then iterate through saved positions of this ship
                    while in_radius_of_point(ship_pos_dict[ships], ship_pos_dict[ship], 0.5) \
                            and counter < len(ship_targets):
                        counter = counter + 1
                        if ships.id != ship.id:
                            # logging.debug(str("COUNTER: " + str(counter)))
                            # if cant find any, stop
                            if counter == len(ship_targets):
                                ship_pos_dict[ship] = Position(ship.x, ship.y)
                                logging.debug("COULDNT FIND ANYTHING HELP2" + " || With counter: " + str(counter))
                                return None
                            ship_pos_dict[ship] = ship_targets[counter][1]
                            better_speed = ship_targets[counter][2]
                            # restart the for loop after its finished
                            restart = True
                            restart_counter = restart_counter + 1
            # use the one with shortest distance to goal as next target
            new_angle = ship.calculate_angle_between(ship_pos_dict[ship])
            logging.debug("TIME2 : " + str(time.time() - start_time))
            logging.debug("ShipNR: " + str(ship.id) + " || Thrust: " + str(better_speed) + " with Angle: " + str(angle))
            return ship.thrust(better_speed, new_angle)

    def is_enemy_ship(self, test_ship):
        for ship in self.enemy_ships:
            if ship == test_ship:
                return True
        return False

    def check_intersection(self, pos1_start: Position, vec1, pos2_start: Position, vec2, threshold):
        pos1_end = Position(pos1_start.x + vec1[0] * 2, pos1_start.y + vec1[1] * 2)
        pos2_end = Position(pos2_start.x + vec2[0] * 2, pos2_start.y + vec2[1] * 2)
        if self.intersect(pos1_start, pos1_end, pos2_start, pos2_end):
            return True
        if in_radius_of_point(pos1_end, pos2_end, threshold * 2):
            return True
        return False

    def create_vector_by_angle(self, angle, speed):
        return [speed * numpy.cos(numpy.radians(angle)),
                speed * numpy.sin(numpy.radians(angle))]

    def create_vector_by_positions(self, pos1: Position, pos2: Position):
        return [pos2.x - pos1.x, pos2.y - pos1.y]

    def ccw(self, a, b, c):
        return (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x)

    # Return true if line segments AB and CD intersect From user Grumdrig on https://stackoverflow.com/questions/3838329/how-can-i-check-if-two-segments-intersect
    def intersect(self, a, b, c, d):
        return self.ccw(a, c, d) != self.ccw(b, c, d) and self.ccw(a, b, c) != self.ccw(a, b, d)


# Basic turn loop. First update our bot, then fetch the commands and send them to the halite engine
bot = Bot(game)
while True:
    start = time.time()
    game_map = game.update_map()
    bot.update(game_map)
    command_queue = bot.command_ships()
    game.send_command_queue(command_queue)
    logging.debug(len(ship_pos_dict))
    logging.debug(ship_pos_dict)
    logging.debug("Time taken: " + str((time.time() - start)))
