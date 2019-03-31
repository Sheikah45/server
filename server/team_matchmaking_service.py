import time
from typing import NamedTuple

from .game_service import GameService
from .decorators import with_logger
from server.lobbyconnection import ClientError
from .players import Player
from .team_matchmaker.player_party import PlayerParty

MapDescription = NamedTuple('Map', [("id", int), ("name", str), ("path", str)])
GroupInvite = NamedTuple('GroupInvite', [("sender", Player), ("recipient", Player), ("party", PlayerParty), ("created_at", float)])

PARTY_INVITE_TIMEOUT = 60 * 60 * 24  # secs

@with_logger
class TeamMatchmakingService:
    """
    Service responsible for managing the global team matchmaking. Does grouping, matchmaking, updates statistics, and
    launches the games.
    """


    def __init__(self, games_service: GameService):
        self.game_service = games_service
        self.player_parties: dict[Player, PlayerParty] = dict()
        self._pending_invites: dict[(Player, Player), GroupInvite] = dict()

    def invite_player_to_party(self, sender: Player, recipient: Player):
        if sender not in self.player_parties:
            self.player_parties[sender] = PlayerParty(self, sender)

        party = self.player_parties.get(sender)

        if not party.owner == sender:
            raise ClientError("You do not own this party.", recoverable=True)

        if sender in recipient.foes:
            raise ClientError("This person doesn't accept invites from you.", recoverable=True)

        self._pending_invites[(sender, recipient)] = GroupInvite(sender, recipient, party, time.time())
        recipient.lobby_connection.send({
            "command": "party_invite",
            "sender": sender.id
        })

    def accept_invite(self, recipient: Player, sender: Player):
        if (sender, recipient) not in self._pending_invites:
            raise ClientError("You're not invited to a party", recoverable=True)

        pending_invite = self._pending_invites.pop((sender, recipient))

        if pending_invite.party not in self.player_parties:
            raise ClientError("The party you're trying to join doesn't exist anymore.", recoverable=True)

        pending_invite.party.add_player(recipient)

        self.remove_disbanded_parties()

    def kick_player_from_party(self, owner: Player, kicked_player: Player):
        if owner not in self.player_parties:
            raise ClientError("You're not in a party.", recoverable=True)

        party = self.player_parties.get(owner)

        if party.owner != owner:
            raise ClientError("You do not own that party.", recoverable=True)

        if kicked_player not in party.members:
            raise ClientError("The kicked player is not in your party.", recoverable=True)

        party.remove_player(kicked_player)

    def leave_party(self, player: Player):
        if player not in self.player_parties:
            raise ClientError("You are not in a party.", recoverable=True)

        self.player_parties.get(player).remove_player(player)
        self.remove_disbanded_parties()

    def clear_invites(self):
        invites = {invite for invite in self._pending_invites.values() if time.time() - invite.created_at >= PARTY_INVITE_TIMEOUT or invite.sender not in self.player_parties}

        for invite in invites:
            self._pending_invites.pop((invite.sender, invite.recipient))

    def remove_party(self, party):
        # party is removed from player_parties dict by disband() removing the key value pair for each player

        party_invites = {invite for invite in self._pending_invites.values() if invite.party == party}
        for invite in party_invites:
            self._pending_invites.pop((invite.sender, invite.recipient))

        party.disband()

    def remove_disbanded_parties(self):
        disbanded_parties = {party for party in self.player_parties.values() if party.is_disbanded()}

        for party in disbanded_parties:
            self.remove_party(party)  # this will call disband again therefore removing all players and informing them

        self.clear_invites()

    def on_player_disconnected(self, player):
        if player in self.player_parties:
            self.leave_party(player)


    # - accept group invite:  client->server
    # - invite to group:  client->server
    # - kick from group:  client->server
    # - leave group:  client->server
    #
    # - group update:  server->client
    #
    #
    #
    # TODO: check if player not in game/hosting/joining when entering queue, then set as in queue
    # TODO: if player single then auto create party on joing queue
    #
    #