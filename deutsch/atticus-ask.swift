// Startet eine Atticus-Frage von außen (z. B. Sprachkurzbefehl „Hey Ava“).
// Bauen: swiftc -O deutsch/atticus-ask.swift -o ~/.local/bin/atticus-ask
import Foundation
DistributedNotificationCenter.default().postNotificationName(.init("atticus.ask"), object: nil, userInfo: nil, deliverImmediately: true)
