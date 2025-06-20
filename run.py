import os
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
from itertools import combinations
from collections import Counter

# GPU 설정
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "1, 2, 3, 4, 5, 6, 7, 8, 9"

# Device configuration
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# 카드 덱 생성
suits = ['♠', '♥', '♦', '♣']
ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
deck = [rank + suit for suit in suits for rank in ranks]

# 카드 순위 값 매핑
rank_value_map = {rank: idx + 2 for idx, rank in enumerate(ranks)}

# 포커 핸드 평가 함수 (기존 코드 재사용)
def evaluate_hand(hole_cards, community_cards):
    all_cards = hole_cards + community_cards
    if len(all_cards) < 5:
        return (0, [0])
    best_rank = (0, [0])
    for combo in combinations(all_cards, 5):
        ranks = [card[:-1] for card in combo]
        suits = [card[-1] for card in combo]
        rank_counts = Counter(ranks)
        rank_values = sorted([rank_value_map[r] for r in ranks], reverse=True)
        is_flush = len(set(suits)) == 1
        is_straight = len(set(rank_values)) == 5 and (max(rank_values) - min(rank_values) == 4)
        if rank_values == [14, 5, 4, 3, 2]:
            is_straight = True
            rank_values = [5, 4, 3, 2, 1]
        if is_flush and is_straight and rank_values[0] == 14:
            rank = (9, rank_values)
        elif is_flush and is_straight:
            rank = (8, rank_values)
        elif 4 in rank_counts.values():
            quad_rank = [k for k, v in rank_counts.items() if v == 4][0]
            kicker = sorted([rank_value_map[k] for k in ranks if k != quad_rank], reverse=True)
            rank = (7, [rank_value_map[quad_rank]] + kicker)
        elif 3 in rank_counts.values() and 2 in rank_counts.values():
            triple = [k for k, v in rank_counts.items() if v == 3][0]
            pair = [k for k, v in rank_counts.items() if v == 2][0]
            rank = (6, [rank_value_map[triple], rank_value_map[pair]])
        elif is_flush:
            rank = (5, rank_values)
        elif is_straight:
            rank = (4, rank_values)
        elif 3 in rank_counts.values():
            triple = [k for k, v in rank_counts.items() if v == 3][0]
            kickers = sorted([rank_value_map[k] for k in ranks if k != triple], reverse=True)
            rank = (3, [rank_value_map[triple]] + kickers)
        elif list(rank_counts.values()).count(2) == 2:
            pairs = sorted([rank_value_map[k] for k, v in rank_counts.items() if v == 2], reverse=True)
            kicker = sorted([rank_value_map[k] for k in ranks if k not in [k for k, v in rank_counts.items() if v == 2]], reverse=True)
            rank = (2, pairs + kicker)
        elif 2 in rank_counts.values():
            pair = [k for k, v in rank_counts.items() if v == 2][0]
            kickers = sorted([rank_value_map[k] for k in ranks if k != pair], reverse=True)
            rank = (1, [rank_value_map[pair]] + kickers)
        else:
            rank = (0, rank_values)
        if rank > best_rank:
            best_rank = rank
    return best_rank

# 몬테카를로 승률 계산 함수 (기존 코드 재사용)
def monte_carlo_win_probability(bot_cards, community_cards, deck, num_simulations=1000):
    wins = 0
    current_deck = deck.copy()
    for card in bot_cards + community_cards:
        if card in current_deck:
            current_deck.remove(card)
    for _ in range(num_simulations):
        sim_deck = current_deck.copy()
        random.shuffle(sim_deck)
        sim_community = community_cards.copy()
        while len(sim_community) < 5:
            sim_community.append(sim_deck.pop())
        opponent_cards = [sim_deck.pop(), sim_deck.pop()]
        bot_rank = evaluate_hand(bot_cards, sim_community)
        opponent_rank = evaluate_hand(opponent_cards, sim_community)
        if bot_rank > opponent_rank:
            wins += 1
        elif bot_rank == opponent_rank:
            wins += 0.5
    return wins / num_simulations

# 포커 게임 환경 클래스
class PokerEnvironment:
    def __init__(self, initial_stack=1000, M=10):
        self.initial_stack = initial_stack
        self.M = M
        self.game = None

    def reset(self):
        self.game = PokerGame(self.initial_stack, self.M)
        return self.game.get_state()

    def step(self, X):
        reward, next_state, done = self.game.step(X)
        return reward, next_state, done

# 포커 게임 클래스
class PokerGame:
    def __init__(self, initial_stack=1000, M=10):
        self.initial_stack = initial_stack
        self.M = M
        self.reset()

    def reset(self):
        self.deck = deck.copy()
        random.shuffle(self.deck)
        self.agent_chips = self.initial_stack
        self.bot_chips = self.initial_stack
        self.pot = 0
        self.agent_bet = 0
        self.bot_bet = 0
        self.community_cards = []
        self.agent_cards = [self.deck.pop(), self.deck.pop()]
        self.bot_cards = [self.deck.pop(), self.deck.pop()]
        self.current_round = 0  # 0: Pre-Flop, 1: Flop, 2: Turn, 3: River
        self.bot_betting_history = [0, 0, 0, 0]  # 각 라운드의 정규화된 베팅 금액
        self.active_players = [1, 2]  # 1: agent, 2: bot
        self.dealer = 1 if random.random() < 0.5 else 2
        self.small_blind = self.M // 2
        self.big_blind = self.M
        self.current_bet = self.big_blind
        if self.dealer == 1:
            self.agent_chips -= self.small_blind
            self.bot_chips -= self.big_blind
            self.agent_bet = self.small_blind
            self.bot_bet = self.big_blind
            self.pot = self.small_blind + self.big_blind
            self.bot_betting_history[0] = self.big_blind / self.initial_stack
        else:
            self.bot_chips -= self.small_blind
            self.agent_chips -= self.big_blind
            self.bot_bet = self.small_blind
            self.agent_bet = self.big_blind
            self.pot = self.small_blind + self.big_blind
            self.bot_betting_history[0] = self.small_blind / self.initial_stack

    def get_state(self):
        win_prob = monte_carlo_win_probability(self.agent_cards, self.community_cards, self.deck)
        state = np.zeros((7, 2))
        state[0] = [win_prob, 1]
        for i in range(4):
            if i < self.current_round:
                state[i + 1] = [self.bot_betting_history[i], 1]
            else:
                state[i + 1] = [0, 0]
        state[5] = [self.agent_chips / self.initial_stack, 1]
        state[6] = [self.bot_chips / self.initial_stack, 1]
        return state.flatten()

    def step(self, X):
        action, bet_amount = self.determine_action(X)
        if action == "fold":
            self.active_players.remove(1)
            return self.get_reward(), self.get_state(), True
        elif action in ["call", "raise"]:
            call_amount = self.current_bet - self.agent_bet if action == "call" else 0
            raise_amount = bet_amount if action == "raise" else 0
            bet = min(call_amount + raise_amount, self.agent_chips)
            self.agent_chips -= bet
            self.agent_bet += bet
            self.pot += bet
            if action == "raise":
                self.current_bet = self.agent_bet

        bot_action, bot_bet = self.bot_decision()
        if bot_action == "fold":
            self.active_players.remove(2)
            return self.get_reward(), self.get_state(), True
        elif bot_action in ["call", "raise"]:
            call_amount = self.current_bet - self.bot_bet if bot_action == "call" else 0
            raise_amount = bot_bet if bot_action == "raise" else 0
            bet = min(call_amount + raise_amount, self.bot_chips)
            self.bot_chips -= bet
            self.bot_bet += bet
            self.pot += bet
            if bot_action == "raise":
                self.current_bet = self.bot_bet
            self.bot_betting_history[self.current_round] = bet / self.initial_stack

        if self.current_round < 3:
            self.current_round += 1
            if self.current_round == 1:
                self.community_cards.extend([self.deck.pop() for _ in range(3)])
            else:
                self.community_cards.append(self.deck.pop())
            self.agent_bet = 0
            self.bot_bet = 0
            self.current_bet = 0
            return 0, self.get_state(), False
        else:
            agent_rank = evaluate_hand(self.agent_cards, self.community_cards)
            bot_rank = evaluate_hand(self.bot_cards, self.community_cards)
            if agent_rank > bot_rank:
                winner = 'A'
            elif bot_rank > agent_rank:
                winner = 'B'
            else:
                winner = 'T'
            return self.get_reward(winner), self.get_state(), True

    def determine_action(self, X):
        C = self.current_bet - self.agent_bet
        U = self.initial_stack * 0.3  # 최대 베팅 한계
        a = self.agent_chips
        if C == 0:  # 먼저 베팅
            if X >= self.M:
                Y = self.M * int(X / self.M)
                Y = min(Y, a, U)
                return "raise", Y
            elif 0 < X < self.M:
                return "check", 0
            else:
                return "check", 0
        else:  # 나중에 베팅
            if X >= 2 * self.M:
                Y = self.M + self.M * int((X - self.M) / self.M)
                Y = min(Y, a, U)
                return "raise", Y
            elif 0 < X < self.M:
                return "fold", 0
            elif self.M <= X < 2 * self.M:
                return "call", 0
            else:
                return "fold", 0

    def bot_decision(self):
        win_prob = monte_carlo_win_probability(self.bot_cards, self.community_cards, self.deck)
        C = self.current_bet - self.bot_bet
        if C > 0:
            if win_prob >= 0.5:
                return "call", C
            else:
                return "fold", 0
        else:
            if win_prob >= 0.9:
                return "raise", min(self.initial_stack * 0.3, self.bot_chips)
            elif win_prob >= 0.7:
                return "raise", self.M
            else:
                return "check", 0

    def get_reward(self, winner=None):
        if winner is None:
            if 1 in self.active_players:
                winner = 'A'
            else:
                winner = 'B'
        if winner == 'A':
            return self.pot / self.initial_stack
        elif winner == 'B':
            return -self.pot / self.initial_stack
        else:
            return 0

# TD3 네트워크 정의
class Actor(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(Actor, self).__init__()
        self.conv1 = nn.Conv2d(1, 16, kernel_size=2, stride=1)
        self.fc1 = nn.Linear(16 * 6 * 1, 128)
        self.fc2 = nn.Linear(128, 128)
        self.fc3 = nn.Linear(128, action_dim)

    def forward(self, state):
        x = state.view(-1, 1, 7, 2)
        x = torch.relu(self.conv1(x))
        x = x.view(x.size(0), -1)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return torch.tanh(self.fc3(x)) * 100  # X 범위: 0~100

class Critic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(Critic, self).__init__()
        self.fc1 = nn.Linear(state_dim + action_dim, 128)
        self.fc2 = nn.Linear(128, 128)
        self.fc3 = nn.Linear(128, 1)

    def forward(self, state, action):
        x = torch.cat([state, action], dim=1)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)

# TD3 에이전트
class TD3Agent:
    def __init__(self, state_dim, action_dim):
        self.actor = Actor(state_dim, action_dim).to(device)
        self.actor_target = Actor(state_dim, action_dim).to(device)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.critic1 = Critic(state_dim, action_dim).to(device)
        self.critic2 = Critic(state_dim, action_dim).to(device)
        self.critic1_target = Critic(state_dim, action_dim).to(device)
        self.critic2_target = Critic(state_dim, action_dim).to(device)
        self.critic1_target.load_state_dict(self.critic1.state_dict())
        self.critic2_target.load_state_dict(self.critic2.state_dict())
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=1e-4)
        self.critic1_optimizer = optim.Adam(self.critic1.parameters(), lr=1e-3)
        self.critic2_optimizer = optim.Adam(self.critic2.parameters(), lr=1e-3)
        self.replay_buffer = deque(maxlen=100000)
        self.batch_size = 64
        self.gamma = 0.99
        self.tau = 0.005
        self.policy_noise = 0.2
        self.noise_clip = 0.5
        self.policy_freq = 2
        self.total_it = 0

    def select_action(self, state):
        state = torch.FloatTensor(np.array(state)).to(device)
        return self.actor(state).cpu().detach().numpy()[0]

    def train(self):
        if len(self.replay_buffer) < self.batch_size:
            return
        self.total_it += 1
        state, action, reward, next_state, done = zip(*random.sample(self.replay_buffer, self.batch_size))
        state = torch.FloatTensor(np.array(state)).to(device)
        action = torch.FloatTensor(np.array(action)).to(device)
        reward = torch.FloatTensor(np.array(reward)).unsqueeze(1).to(device)
        next_state = torch.FloatTensor(np.array(next_state)).to(device)
        done = torch.FloatTensor(np.array(done)).unsqueeze(1).to(device)

        with torch.no_grad():
            noise = (torch.randn_like(action) * self.policy_noise).clamp(-self.noise_clip, self.noise_clip)
            next_action = (self.actor_target(next_state) + noise).clamp(0, 100)
            target_Q1 = self.critic1_target(next_state, next_action)
            target_Q2 = self.critic2_target(next_state, next_action)
            target_Q = reward + (1 - done) * self.gamma * torch.min(target_Q1, target_Q2)

        current_Q1 = self.critic1(state, action)
        current_Q2 = self.critic2(state, action)
        critic_loss = nn.MSELoss()(current_Q1, target_Q) + nn.MSELoss()(current_Q2, target_Q)

        self.critic1_optimizer.zero_grad()
        self.critic2_optimizer.zero_grad()
        critic_loss.backward()
        self.critic1_optimizer.step()
        self.critic2_optimizer.step()

        if self.total_it % self.policy_freq == 0:
            actor_loss = -self.critic1(state, self.actor(state)).mean()
            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.actor_optimizer.step()

            for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
                target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)
            for param, target_param in zip(self.critic1.parameters(), self.critic1_target.parameters()):
                target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)
            for param, target_param in zip(self.critic2.parameters(), self.critic2_target.parameters()):
                target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

    def add_experience(self, state, action, reward, next_state, done):
        self.replay_buffer.append((state, action, reward, next_state, done))

# 학습 루프
def train():
    env = PokerEnvironment()
    agent = TD3Agent(state_dim=14, action_dim=1)
    episodes = 1000
    for episode in range(episodes):
        state = env.reset()
        done = False
        total_reward = 0
        while not done:
            action = agent.select_action(state)
            reward, next_state, done = env.step(action)
            agent.add_experience(state, action, reward, next_state, done)
            agent.train()
            state = next_state
            total_reward += reward
        if episode % 100 == 0:
            print(f"Episode {episode}, Total Reward: {total_reward}")
            torch.save(agent.actor.state_dict(), f"actor_episode_{episode}.pt")
            torch.save(agent.critic1.state_dict(), f"critic1_episode_{episode}.pt")
            torch.save(agent.critic2.state_dict(), f"critic2_episode_{episode}.pt")

if __name__ == "__main__":
    train()
