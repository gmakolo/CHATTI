# CHATTI — Complete Application Upgrade Prompt

Upgrade my existing CHATTI application by implementing the features, improvements, and bug fixes listed below.

## IMPORTANT INSTRUCTIONS

- Work on my existing CHATTI project. Do not rebuild it from scratch.
- Inspect the existing code before making changes.
- Preserve all existing users, messages, friendships, posts, and database data.
- Never delete or recreate the existing database.
- Use safe database migrations.
- Reuse existing routes, models, templates, authentication, and storage where possible.
- Fix broken features instead of creating duplicate ones.
- Test actual functionality, not just the appearance of buttons.
- Implement the work in manageable stages and test each stage before proceeding.

# 1. CHATTI Branding and Colours

Our official primary brand colour is Electric Violet (#7C3AED).

Use these supporting colours:
- Electric Violet: #7C3AED
- Soft Lavender: #EDE9FE
- White: #FFFFFF
- Dark Navy: #1E293B
- Dark Background: #0F172A
- Dusty Mauve: #8B5E83

Fix the existing problem where CHATTI appears white instead of Electric Violet.

Apply the branding consistently to the logo, buttons, icons, navigation, links, highlights, Home, Chats, People, Explore, Updates, Profile, Settings, camera, and menus.

Fix CSS variables, theme settings, templates, or stylesheets that override the brand colour. Do not simply change the logo.

Ensure light and dark modes affect the entire application, including backgrounds, cards, navigation, message bubbles, forms, and menus.

# 2. Login and Passwords

- Add a Show Password checkbox to login and registration forms.
- Let users choose whether to see their password while typing.
- Enforce the requested maximum password length of 8 characters for new passwords.
- Display: "Password cannot be more than 8 characters." when the limit is exceeded.
- Validate passwords on the frontend and backend.
- Store passwords securely using proper password hashing.
- Preserve existing accounts and login functionality.

# 3. Fix All 10 Chat Colour Themes

The existing Chat Color menu displays colour options, but selecting them does not change the chat appearance. Fix the entire feature.

Provide these 10 themes:

1. Violet and Lavender
2. Lavender Mist
3. Electric Violet
4. Soft Lavender
5. Lavender Light
6. Dusty Mauve
7. Bright White
8. Midnight Violet
9. Rose Lavender
10. Deep Purple

Requirements:
- Make every option clickable.
- Apply the selected theme immediately to the chat background, sent and received message bubbles, and appropriate highlights.
- Show the selected theme clearly.
- Save each user's theme preference for the appropriate conversation.
- Restore the theme after refreshing or reopening a conversation.
- Prevent one conversation's theme from accidentally changing another.
- Support light and dark modes.
- Inspect JavaScript, event listeners, Flask routes, database updates, and CSS conflicts to identify the actual cause of the current failure.
- Test every theme individually and verify persistence.

Do not claim the feature works until all 10 themes have been tested.

# 4. Home Page and Post Privacy

Improve the Create Post feature on Home so users can choose who sees each post.

Provide these audience options:

**Public:** Everyone can view the post according to the application's access rules.

**Private:** Only the author can view the post.

**Friends:** Only accepted friends can view the post.

**Selected People:** Allow the author to search for friends and select multiple people. Only the author and selected people can view the post.

**Specific Group:** Allow the author to select an existing group. Only authorised group members and the author can view the post.

Requirements:
- Place the audience selector near the Post button.
- Show a privacy icon and audience label on each post.
- Save the audience setting in the database.
- Allow authors to change the audience of existing posts.
- Apply permission changes immediately.
- Respect privacy in Home, Explore, search, previews, comments, reactions, and reshares.
- Prevent unauthorised access through direct URLs or backend requests.
- Only allow authors to edit or delete their own posts.
- Implement group support safely if it does not already exist.
- Give existing posts a sensible default audience without accidentally exposing private content.

Privacy must be enforced on the backend, not just by hiding posts in the interface.

# 5. Horizontal Updates Display

Redesign the existing Updates section to display updates horizontally, similar to WhatsApp Status.

- Display one horizontal, scrollable row of circular profile pictures.
- Put "My Update" first with a plus (+) button.
- Display friends' updates with usernames underneath.
- Support swiping on mobile and scrolling on desktop.
- Show a coloured ring around profiles with unseen updates.
- Keep the design compact and modern.
- Do not display updates vertically or as a large list.
- Use Electric Violet as the primary brand colour.

# 6. Full-Screen Updates Viewer

When someone clicks an update:
- Open it in a full-screen viewer.
- Add left and right navigation between updates.
- Show the author's profile picture and username.
- Display the exact posting date/time and relative time, such as "2 minutes ago."
- Show the time remaining before expiry.
- Include a close button.
- Support images, videos, and text updates.
- Allow reactions, private replies, and available interactions.
- Make the viewer responsive on mobile and desktop.

# 7. Snapchat-Style Camera and Photo Filters

Upgrade the existing Updates feature with a camera that lets users take pictures with filters, similar to Snapchat.

## A. Camera Access

When users tap "Add Update", provide options to:
- Open the camera.
- Upload an existing picture from their gallery.
- Switch between the front and back cameras.
- Take a picture using the selected camera.
- Preview the picture before posting.

Request camera permission when necessary. Explain clearly if permission is denied or the device does not support the camera.

Use browser camera APIs where supported. Handle camera errors, unavailable cameras, and unsupported browsers gracefully.

## B. Ten Camera Filters

Provide these filters:

1. Natural
2. Black and White
3. Vintage
4. Warm
5. Cool
6. Golden Glow
7. Soft Pink
8. Purple Glow
9. Bright
10. Dreamy

Requirements:
- Display filter choices clearly in the camera interface.
- Let users preview each filter before taking a picture.
- Apply filters to the live camera preview where technically supported.
- If live filtering is unavailable, apply the selected filter immediately after capture.
- Allow users to switch filters without taking another picture.
- Allow users to remove the selected filter and return to the original image.
- Make filter previews work on mobile and desktop where supported.

## C. Photo Editing

After taking or selecting a picture, allow users to:

- Change or remove the filter.
- Adjust brightness and contrast.
- Crop the picture.
- Rotate the picture.
- Add text and emojis.
- Move and resize text and emojis.
- Choose readable text colours and styles.
- Preview the finished image before posting.
- Cancel editing and return to the camera or gallery selection.

Make editing controls easy to use on mobile screens.

## D. Posting Camera Updates

- Add a clear "Post Update" button.
- Save the final edited image using CHATTI's existing upload and storage system.
- Display the image in the existing horizontal Updates row.
- Open the image in the existing full-screen Updates viewer.
- Show the author's profile picture, username, and posting time.
- Apply the existing 12-hour expiry rule.
- Show a success or error message after posting.
- Prevent duplicate submissions when the user taps Post repeatedly.

## E. Camera Privacy and Security

- Validate uploaded image types and enforce reasonable file-size limits.
- Validate uploads on the backend.
- Use safe filenames and the existing storage architecture.
- Prevent private images from being accessed by unauthorised users.
- Respect update audience settings.
- Do not expose internal file paths or sensitive information.
- Do not upload images without the user's explicit action.

## F. Camera Design

- Use Electric Violet (#7C3AED).
- Make the camera interface modern and attractive.
- Keep the capture button, camera switch, filter choices, and editing controls easy to reach.
- Make the interface responsive on mobile and desktop.
- Integrate it into the existing Add Update process rather than creating a separate, disconnected feature.

## G. Camera Testing

Test:
- Opening and closing the camera.
- Front and back camera switching.
- Camera permission handling.
- Taking pictures.
- Uploading pictures from the gallery.
- All 10 filters.
- Brightness and contrast adjustments.
- Cropping and rotation.
- Text and emoji overlays.
- Previewing edited pictures.
- Posting and displaying updates.
- Private image access.
- Automatic expiry after 12 hours.

Do not report the camera as complete unless the supported features have been tested.

# 8. Colourful Text Updates

Allow users to create text-only updates with:
- Colourful backgrounds.
- Different readable font styles.
- Emojis.
- A live preview.
- Reasonable text-length limits.

Display text updates in the horizontal Updates row and open them in the full-screen viewer.

# 9. Poll Updates

Allow users to create polls inside Updates.

- Add a question and multiple answer options.
- Allow eligible viewers to vote.
- Prevent repeated voting by the same user.
- Display vote totals and percentages.
- Let the poll creator view results.
- Enforce access and voting rules on the backend.
- Expire polls when their parent update expires.

# 10. Update Reactions

Add these quick reactions:

- ❤️ Love
- 😂 Laugh
- 😮 Surprise
- 😢 Sad
- 👍 Like
- 🔥 Fire

Save reactions in the database. Let authors see who reacted and which reaction was used. Prevent duplicate reactions unless a user changes their reaction.

Do not allow reactions to expired or inaccessible updates.

# 11. Private Replies to Updates

Allow users to reply privately to an update through CHATTI's existing messaging system.

- Send the reply as a private message.
- Include a reference or preview of the original update.
- Never publish private replies publicly.
- Respect messaging restrictions and privacy settings.

# 12. Update Views and Privacy

Allow authors to:
- See who viewed their updates.
- View the total number of views.
- Choose who can see each update.

Audience options:
- Everyone.
- Friends only.
- Selected people.

Enforce privacy on the backend. Prevent unauthorised users from seeing private updates or viewer information. Avoid repeatedly counting the same viewer as multiple unique viewers for one update.

# 13. Reshare Updates

Allow users to reshare updates where permitted.

- Credit the original author.
- Do not allow expired or deleted updates to be reshared.
- Respect the original update's privacy settings.
- Never allow resharing to bypass privacy restrictions.
- Keep the original author's identity visible.

# 14. Update Management and Expiry

- Allow users to delete their own updates.
- Prevent users from editing or deleting other people's updates.
- Display exact posting times and relative times.
- Show clear success and error messages.
- Allow previewing before posting.
- Expire updates automatically 12 hours after posting, regardless of whether they have been viewed.
- Hide expired updates and prevent further interaction.
- Keep Home posts and ordinary chat messages unaffected.

# 15. Chat Features

Preserve and improve existing messaging functionality.

### Messaging
- Keep one-to-one messaging working.
- Add a typing indicator.
- Add an emoji picker with a searchable keyword bar for words such as "laugh", "cry", "smile", and "love".
- Ensure the emoji picker does not cover important parts of the conversation or message input.
- Support picture messages.
- Support view-once pictures according to clearly defined rules.
- Support read receipts where enabled.
- Support voice notes if compatible with the existing architecture.
- Preserve existing message history.

### Pending Friend Request Message Limit

When a user sends a friend request to someone who has not accepted it:
- Allow a maximum of three messages from the sender to that recipient.
- Block further messages until the request is accepted.
- Display a warning using the recipient's actual username: "You can't send more messages until Alex accepts your friend request."
- Empty or rejected messages must not consume the limit.
- Enforce the limit on the backend.
- Preserve counts across refreshes and logouts.
- Remove the restriction when the request is accepted.

Inspect the existing friendship and messaging logic before implementing this.

# 16. People, Friends, and Groups

- Preserve the existing People feature.
- Support discovering people.
- Support sending, accepting, rejecting, and cancelling friend requests where appropriate.
- Allow users to add and remove friends.
- Display relevant profile information.
- Support group selection for private posts.
- Reuse existing group features rather than creating duplicates.
- Implement missing group support safely where necessary.

# 17. Profile Improvements

Allow users to edit their own:
- Full name.
- Username.
- Email.
- Birthday.
- Gender, optional.
- Bio.
- Location, optional.
- Interests and hobbies.
- Occupation.
- Profile picture.

Requirements:
- Save registration email and make it accessible to the account owner.
- Hide email from other users by default.
- Keep birthday private by default, with a visibility option.
- Allow optional fields to remain blank.
- Validate profile changes on the backend.
- Prevent users from editing other people's profiles.
- Preserve existing profile data.

# 18. Privacy and Account Settings

Make existing settings functional and persistent.

Include:
- Online status visibility.
- Last-active visibility.
- Read receipts as a separate setting.
- Message retention options: when seen, 12 hours, 24 hours, 30 days, or off.
- Profile privacy.
- Birthday privacy.
- Update audience settings.
- Appropriate account and privacy controls.

Apply settings to the relevant features. Do not silently delete existing data when preferences change.

# 19. Home Page and Navigation

Use this navigation order:

1. Home
2. Chats
3. People
4. Explore
5. Updates
6. Profile
7. Settings

### Home
- Display a welcome section.
- Include the Create Post composer.
- Show the community feed for ideas, dreams, discussions, and other posts.
- Include the horizontal Updates row.
- Do not add a large Find New People panel.
- Do not duplicate the Chats list.

### Chats
- Show all conversations, not only recent ones.
- Provide search and filters for All Chats, Unread, Groups, and Archived where supported.
- Display profile pictures, usernames, last messages, timestamps, and unread counts.
- Do not duplicate the People list.

### People
Keep friend discovery, friend requests, and friend management here.

### Responsive Design
Use compact navigation and suitable mobile navigation. Make posts, forms, camera controls, chat interfaces, and menus responsive.

# 20. Database Safety and Security

- Inspect the existing schema before making changes.
- Use safe database migrations.
- Never delete or recreate the database.
- Preserve users, passwords, messages, friendships, posts, and settings.
- Validate input on the backend.
- Enforce access permissions on the backend.
- Protect private posts, updates, images, and profile information.
- Validate uploaded files.
- Prevent duplicate records and unsafe database operations.
- Handle failed operations without corrupting existing data.
- Keep authentication and password hashing secure.

# 21. Implementation and Testing Process

Follow this order:

1. Inspect the repository and current implementation.
2. Identify existing, missing, and broken features.
3. Create a backup or commit the current code.
4. Fix Electric Violet branding.
5. Fix and test all 10 chat colour themes.
6. Implement post audience selection and backend privacy.
7. Implement horizontal Updates and the full-screen viewer.
8. Implement the Snapchat-style camera, all 10 filters, photo editing, text updates, polls, reactions, private replies, views, and reshares.
9. Improve messaging, profiles, navigation, and settings.
10. Apply safe database migrations.
11. Run existing tests and add tests for new functionality.
12. Test on mobile and desktop where possible.
13. Fix errors introduced by the changes.
14. Report completed features, modified files, migrations, test results, and remaining limitations.

Use multiple test accounts to verify privacy and permissions. Test every chat theme individually and verify that preferences persist after refreshing.

Do not mark a feature complete just because its button appears. Verify the actual behaviour, database persistence, and backend permissions.

## Final Requirements

Keep CHATTI's existing architecture and data. Maintain the Electric Violet brand, protect user privacy, and deliver a reliable, responsive interface.

Because this is a large upgrade, work in small, tested stages. Do not make all changes at once without checking for regressions. If a feature cannot be completed, explain the limitation honestly rather than claiming it works.
# 23. Message Sent and Unread Notification Icons

- When a user sends a message successfully, show a small sent indicator beside the message.
- Use ✓ for sent, ✓✓ for delivered, and ✓✓ in violet or another clear style for read, if the app supports read receipts.
- When a user receives a new message they haven't opened, show an unread notification badge on the Chats icon and beside that conversation.
- Display the number of unread messages, such as 1, 2, or 9+.
- Clear the unread badge when the user opens the conversation and views the messages.
- Update notifications immediately without requiring a page refresh.
- Save unread status in the database so it remains correct after refreshing or logging out and back in.
- Count only genuinely unread messages and prevent duplicate counts.
- Make the icons and badges clear on both light and dark themes, using CHATTI's Electric Violet branding.
- Test sent, delivered, read, and unread indicators with two user accounts. Ensure the counts update correctly and messages are not marked as read before the recipient views them.

# 24. Dark Background and Theme Upgrade

- Replace the plain white background with a modern, elegant dark violet theme that supports both dark and light modes.
- Make Dark Mode the default theme.
- Use these colours:
  - Main background: `#0F0B1A` — deep violet-black.
  - Cards and sidebars: `#1A1428` — dark purple.
  - Chat areas: `#211936` — soft dark violet.
  - Primary colour: `#7C3AED` — Electric Violet.
  - Highlight colour: `#A78BFA` — light lavender.
  - Main text: `#F8FAFC` — soft white.
  - Secondary text: `#C4B5FD` — light lavender.
- Make buttons, message bubbles, inputs, navigation, notifications, and pop-ups match the theme.
- Keep text clear and readable, with enough contrast.
- Ensure all 10 chat colour themes still work correctly.
- Add a working Light Mode/Dark Mode switch in Settings, and remember the user's choice after refreshing or logging in again.
- Remove conflicting CSS that forces the app background to white. Fix the root cause rather than adding temporary overrides.
- Make the design responsive on phones and computers.
- Test every page in both modes to ensure no white backgrounds appear unexpectedly and all text remains readable.
