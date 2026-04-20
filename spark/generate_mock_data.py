import csv
import os

def generate_mock_data():
    data = [
        ["subject", "message", "isSpam"],
        ["Meeting tomorrow", "Hi, let's meet tomorrow at 10am to discuss the project.", 0],
        ["Quarterly Report", "The report for Q1 is ready. Please review and provide feedback.", 0],
        ["Lunch?", "Hey, do you want to grab lunch today? I'm thinking about that Italian place.", 0],
        ["Project Update", "The deployment was successful. All systems are operational.", 0],
        ["Vacation request", "I would like to take next Friday off. Let me know if that works.", 0],
        ["URGENT: WINNER!", "CONGRATULATIONS! You have won a $1000 gift card. Click here to claim now!!!", 1],
        ["Work from home opportunity", "Earn $5000 per week working from home! No experience needed. Join now!", 1],
        ["Your account is locked", "Suspicious activity detected. Click this link to verify your identity and unlock your account.", 1],
        ["Get rich quick", "Invest $100 and get $1000 in just 24 hours! Guaranteed returns!", 1],
        ["Cheap meds", "Buy cheap medications online without prescription. Best prices guaranteed!", 1],
    ]
    
    os.makedirs("data", exist_ok=True)
    with open("data/enron_spam_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(data[0]) # Header
        for _ in range(50): # Repeat rows to simulate more data
            writer.writerows(data[1:])
            
    print("Generated mock data at data/enron_spam_data.csv")

if __name__ == "__main__":
    generate_mock_data()
