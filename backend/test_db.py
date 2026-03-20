import asyncio
import os
from dotenv import load_dotenv
from app.schemas.auth import UserRegister
from app.services.auth_service import register_user, _get_service_client

async def main():
    print("🚀 Đang tải biến môi trường từ app/.env...")
    load_dotenv("app/.env")

    print(f"🔗 SUPABASE_URL: {os.getenv('SUPABASE_URL')}")
    print("Testing connection...")

    # Test kết nối trực tiếp đến bảng users (bằng role service_role để đọc thông tin public)
    try:
        service_client = _get_service_client()
        res = service_client.table("users").select("id", count="exact").limit(1).execute()
        print("✅ Kết nối đến Database thành công!")
        print(f"📊 Tổng số users hiện có trong bảng public.users: {res.count}")
    except Exception as e:
        print(f"❌ Kết nối đến database thất bại: {e}")
        return

    import time
    # Thêm user mẫu bằng Admin API (Bypass Rate Limit của Supabase)
    print("\n📝 Thêm 1 user mẫu mới (Admin Bypass)...")
    email = f"test_user_lotus_{int(time.time())}@gmail.com"
    
    try:
        service_client = _get_service_client()
        
        # 1. Admin tạo user (bỏ qua email Rate Limit / CAPTCHA)
        admin_auth_res = service_client.auth.admin.create_user({
            "email": email,
            "password": "Str0ngPassword!123",
            "email_confirm": True
        })
        user_id = str(admin_auth_res.user.id)
        print("✅ Đã gọi Admin API tạo Auth User thành công!")
        
        # 2. Cập nhật thêm thông tin vào public.users giống hàm register_user
        service_client.table("users").update({
            "full_name": "Người Dùng Thử Nghiệm",
            "role": "patient"
        }).eq("id", user_id).execute()
        
        # 3. Đọc lên để kiểm tra xem trigger đã hoạt động chưa
        res = service_client.table("users").select("*").eq("id", user_id).single().execute()
        
        print(f"\n👤 Thông tin User Profile trong public.users (Chứng tỏ Database Trigger ĐÃ CHẠY!):")
        print(f"   => ID: {res.data['id']}")
        print(f"   => Email: {res.data['email']}")
        print(f"   => Full Name: {res.data['full_name']}")
        print(f"   => Role: {res.data['role']}")
        print(f"   => Đăng ký ngày: {res.data['created_at']}")
        
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        print("   => Nếu Lỗi 404/0 rows: Bạn chưa chạy file data/auth_trigger.sql trong Supabase SQL Editor!")


if __name__ == "__main__":
    asyncio.run(main())
