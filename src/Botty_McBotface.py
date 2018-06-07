# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Scripted agents."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from pysc2.agents import base_agent
from pysc2.lib import actions
from pysc2.lib import features

import numpy as np
import math
import random

import actions as our_actions
from RLBrain import RLBrain
from Learner import GameState
from BuildQueues import BuildingQueue, UnitQueue, ResearchQueue, Zerg

_PLAYER_RELATIVE = features.SCREEN_FEATURES.player_relative.index
_PLAYER_SELF = 1
_PLAYER_FRIENDLY = 1
_PLAYER_NEUTRAL = 3  # beacon/minerals
_PLAYER_HOSTILE = 4
_NEUTRAL_VESPENE_GEYSER = 342
_UNIT_TYPE = features.SCREEN_FEATURES.unit_type.index
_NO_OP = actions.FUNCTIONS.no_op.id
_MOVE_SCREEN = actions.FUNCTIONS.Move_screen.id
_ATTACK_SCREEN = actions.FUNCTIONS.Attack_screen.id
_SELECT_ARMY = actions.FUNCTIONS.select_army.id
_BUILD_EXTRACTOR = actions.FUNCTIONS.Build_Extractor_screen_screen.id
_NOT_QUEUED = [0]
_SELECT_ALL = [0]

_MAP_SIZE = 128
# Size will depend on screen size.
_SIZE_VESPENE = 97

smart_actions = [
    'no_op',
    'build_building',
    'build_units',
    'build_workers',
    'research',
    'cancel',
    'attack',
    'defend',
    'patrol',
    'return_to_base'
]

# Want a Square * Square move view action space.
_SQUARE = 8
for move_view_x in range(_MAP_SIZE):
    for move_view_y in range(_MAP_SIZE):
        if move_view_x % _SQUARE == 0 and move_view_y % _SQUARE == 0:
            smart_actions.append('move_view_' + str(move_view_x) + '_' + str(move_view_y))

# Put in offsets for where to store buildings. Extractor is a special case.
building_offsets = {
    '_BUILD_HATCHERY': [0, 0],
    '_BUILD_SPAWNING_POOL': [],
    '_BUILD_SPINE_CRAWLER': [],
    '_BUILD_EXTRACTOR': [0, 0],
    '_BUILD_ROACH_WARREN': [],
    '_BUILD_LAIR': [],
    '_BUILD_HYDRALISK_DEN': [],
    '_BUILD_SPORE_CRAWLER': [],
    '_BUILD_EVOLUTION_CHAMBER': [],
    '_BUILD_HIVE': [],
    '_BUILD_ULTRA_CAVERN': []
}


class Botty(base_agent.BaseAgent):
    def __init__(self):
        super(Botty, self).__init__()
        self.strategy_manager = RLBrain(smart_actions)  # keeping default rates for now.
        self.state = GameState()

        # if we want to have predefined initialization actions, we can hard code values in here.
        self.action_list = []
        self.prev_action = None
        self.prev_state = None
        self.base = 'right'
        self.building_queue = BuildingQueue()
        self.unit_queue = UnitQueue()
        self.research_queue = ResearchQueue()

    def init_base(self, obs):
        """method to set the location of the base."""
        x, y = (obs.observation['minimap'][_PLAYER_RELATIVE] == _PLAYER_SELF).nonzero()

        if y.any() and y.mean() <= _MAP_SIZE // 2:
            self.base = 'left'
        else:
            self.base = 'right'

    def step(self, obs):
        """
        1. reduce state.
        2. Allow brain to learn based prev action, state, & rewards
        3. Choose action based on current state.
        4. Update prev actions & state.
        5. Do action. My current idea is to store many actions in an action list.
           This will allow our abstracted actions to do a lot more per action.
        :param obs: The observation of current step.
        :return: A function ID for SC2 to call.
        """
        super(Botty, self).step(obs)

        # gives us info about where our base is. Left side or right side. Works for 2 base pos maps.
        if not self.prev_state and not self.prev_action:
            self.init_base(obs)

        if self.action_list:
            return self.action_list.pop()

        self.state.update(obs)
        self.reward_and_learn()

        if self.state not in self.strategy_manager.QTable.index:
            self.strategy_manager.add_state(self.state)
            action = self.strategy_manager.choose_action(self.state)
        else:
            action = self.strategy_manager.choose_action(self.state)

        self.prev_state, self.prev_action = self.state, action

        # Gets the abstracted action functions out the actions.py (as our_actions) file.

        self.action_list = self.get_action_list(action, obs)
        return self.action_list.pop()

    def reward_and_learn(self):
        if self.prev_action and self.prev_state:
            # Update the reward, we going to need to give it to Brain/
            reward = 0

            # Todo finish reward stuff
            self.strategy_manager.learn(self.prev_state, self.state, self.prev_action, reward)

    def get_action_list(self, action_str, obs):
        """ This function will set up the appropriate args for the various actions."""
        if 'move_view' in action_str:
            move_view_id, x, y = action_str.split('_')
            action_function = getattr(our_actions, move_view_id)
            return action_function(obs, x, y)

        action_function = getattr(our_actions, action_str)

        if action_str == 'no_op':
            return action_function()
        elif action_str == 'build_building':
            building = self.building_queue.dequeue(obs)
            target = self.get_building_target(obs, building)
            return action_function(building, target)
        elif action_str == 'build_units':
            return action_function(self.unit_queue.dequeue(obs))
        elif action_str == 'build_worker':
            return action_function(actions.FUNCTIONS.Train_Drone_quick.id)
        elif action_str == 'research':
            return action_function(self.research_queue.dequeue(obs))
        elif action_str == 'attack':
            return action_function(obs)
        elif action_str == 'defend':
            unit_type = obs.observation['screen'][_UNIT_TYPE]
            hatchery_x, hatchery_y = (unit_type == Zerg.Hatchery).nonzero()
            return action_function(hatchery_x.mean() + 10, hatchery_y.mean() + 10)
        elif action_str == 'return_to_base':
            unit_type = obs.observation['screen'][_UNIT_TYPE]
            hatchery_x, hatchery_y = (unit_type == Zerg.Hatchery).nonzero()
            return action_function(hatchery_x + 10, hatchery_y + 10)

        return []

    @staticmethod
    def get_building_target(obs, building):
        unit_type = obs.observation['screen'][_UNIT_TYPE]
        if building == _BUILD_EXTRACTOR:
            vespene_y, vespene_x = (unit_type == _NEUTRAL_VESPENE_GEYSER).nonzero()
            # Two options. Use a classifier to group vespene coordinates,
            # OR we can choose randomly and hope we don't get a unit.
            # For now I will do the later.
            i = random.randint(0, len(vespene_y) - 1)
            return [vespene_x[i], vespene_y[i]]
        else:
            # Building may not pass into dict correctly as a key.
            x_offset, y_offset = building_offsets[str(building)]
            hatchery_x, hatchery_y = (unit_type == Zerg.Hatchery).nonzero()
            return [hatchery_x.mean() + x_offset, hatchery_y.mean() + y_offset]

    def transform_location(self, x, x_distance, y, y_distance):
        if self.base == 'right':
            return [x - x_distance, y - y_distance]

        return [x + x_distance, y + y_distance]


# I FIGURED THIS PAGE WOULD BLOAT DUE TO BOT ANYWAYS SO I'VE MOVED ACTIONS INTO A SEPARATE FILE


class DefeatRoaches(base_agent.BaseAgent):
    """An agent specifically for solving the DefeatRoaches map."""

    def step(self, obs):
        super(DefeatRoaches, self).step(obs)
        if _ATTACK_SCREEN in obs.observation["available_actions"]:
            player_relative = obs.observation["screen"][_PLAYER_RELATIVE]
            roach_y, roach_x = (player_relative == _PLAYER_HOSTILE).nonzero()
            if not roach_y.any():
                return actions.FunctionCall(_NO_OP, [])
            index = np.argmax(roach_y)
            target = [roach_x[index], roach_y[index]]
            return actions.FunctionCall(_ATTACK_SCREEN, [_NOT_QUEUED, target])
        elif _SELECT_ARMY in obs.observation["available_actions"]:
            return actions.FunctionCall(_SELECT_ARMY, [_SELECT_ALL])
        else:
            return actions.FunctionCall(_NO_OP, [])


class MoveToBeacon(base_agent.BaseAgent):
    """An agent specifically for solving the MoveToBeacon map."""

    def step(self, obs):
        super(MoveToBeacon, self).step(obs)
        if _MOVE_SCREEN in obs.observation["available_actions"]:
            player_relative = obs.observation["screen"][_PLAYER_RELATIVE]
            neutral_y, neutral_x = (player_relative == _PLAYER_NEUTRAL).nonzero()
            if not neutral_y.any():
                return actions.FunctionCall(_NO_OP, [])
            target = [int(neutral_x.mean()), int(neutral_y.mean())]
            return actions.FunctionCall(_MOVE_SCREEN, [_NOT_QUEUED, target])
        else:
            return actions.FunctionCall(_SELECT_ARMY, [_SELECT_ALL])