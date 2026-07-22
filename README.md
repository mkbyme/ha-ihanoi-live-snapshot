# ha-ihanoi-live-snapshot
Công cụ thực hiện lấy ảnh snapshot từ live cam trên app iHanoi


Dựa theo thư viện thuật toán đã làm ở trong ,/working hãy tạo 1 hacs cho home assistaint 

Trên Đó sẽ cấu hình tạo thực thể ảnh cho Camera được thêm từ dropdown danh sách cam.

Mỗi cam sẽ có thêm 1 trigger cập nhật có thể dùng để gọi qua automation, sau khi update xong sẽ lưu lại ảnh mới và thời gian cập nhật

Tham khảo từ hacs đã có hãy build config trên /home/nxcuong/Desktop/mine/homeassistant/ha-toanthanggps-com

Lưu tên thực thể là tên cam (đã rút gọn dưới 100 ký tự lấy từ tên của cam trong danh sách "name": "P.V.Đồng - Bến Xe Nam Thăng Long - C192.12-PTZ", )

Và có 1 thực thể để bấm update danh sách camera.json khi cần. file camera,json đó là file mang đi sẵn.